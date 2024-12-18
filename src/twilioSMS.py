from typing import ClassVar, Mapping, Sequence, Any, Dict, Optional, Tuple, Final, List, cast
from typing_extensions import Self
from typing import Final

from viam.resource.types import RESOURCE_NAMESPACE_RDK, RESOURCE_TYPE_SERVICE, Subtype
from viam.module.types import Reconfigurable
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName, Vector3
from viam.resource.base import ResourceBase
from viam.resource.types import Model, ModelFamily
from viam.utils import ValueTypes, struct_to_dict
from viam.app.viam_client import ViamClient
from viam.rpc.dial import Credentials, DialOptions

from viam.services.generic import Generic
from viam.logging import getLogger

from datetime import datetime, timedelta
import pytz
import bson
import uuid
import json
import asyncio
import requests
import mimetypes
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from twilio.rest import Client

LOGGER = getLogger(__name__)

class twilioSMS(Generic, Reconfigurable):

    MODEL: ClassVar[Model] = Model(ModelFamily("mcvella", "messaging"), "twilio-sms")
    name: str
    twilio_client: Client
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_media_sid: str
    default_from: str
    enforce_preset: bool
    preset_messages: dict
    app_client: None
    api_key_id: str
    api_key: str
    organization_id: str
    part_id: str
    run_loop: bool = False
    store_log_in_data_management: bool = False

    # Constructor
    @classmethod
    def new(cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> Self:
        my_class = cls(config.name)
        my_class.reconfigure(config, dependencies)
        return my_class

    # Validates JSON Configuration
    @classmethod
    def validate(cls, config: ComponentConfig):
        account_sid = config.attributes.fields["account_sid"].string_value
        if account_sid == "":
            raise Exception("An account_sid must be defined")
        auth_token = config.attributes.fields["auth_token"].string_value
        if auth_token == "":
            raise Exception("An auth_token must be defined")
        enforce_preset = config.attributes.fields["enforce_preset"].bool_value
        if enforce_preset == True:
            attributes = struct_to_dict(config.attributes)
            preset_messages = attributes.get("preset_messages")
            if preset_messages is None:
                raise Exception("preset_messages must be defined when enforce_preset is set to true")
        return

    # Handles attribute reconfiguration
    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        self.run_loop = False

        self.twilio_account_sid = config.attributes.fields["account_sid"].string_value
        self.twilio_auth_token = config.attributes.fields["auth_token"].string_value
        self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
        self.twilio_media_sid = config.attributes.fields["media_sid"].string_value or ""
        self.default_from = config.attributes.fields["default_from"].string_value or ""
        self.enforce_preset = config.attributes.fields["enforce_preset"].bool_value or False
        attributes = struct_to_dict(config.attributes)
        self.preset_messages = attributes.get("preset_messages") or {}
        self.store_log_in_data_management = config.attributes.fields["store_log_in_data_management"].bool_value or False
        self.api_key = config.attributes.fields["app_api_key"].string_value or ''
        self.api_key_id = config.attributes.fields["app_api_key_id"].string_value or ''
        self.organization_id = config.attributes.fields["organization_id"].string_value or ''
        self.part_id = config.attributes.fields["part_id"].string_value or ''

        self.name = config.name

        self.run_loop = True
        if self.store_log_in_data_management:
            asyncio.ensure_future(self.log_check())

        return
    
    async def viam_connect(self) -> ViamClient:
        dial_options = DialOptions.with_api_key( 
            api_key=self.api_key,
            api_key_id=self.api_key_id
        )
        return await ViamClient.create_from_dial_options(dial_options)
    
    async def log_check(self):
        LOGGER.info("Starting Twilio log check loop")
        
        if (self.api_key != '' and self.api_key_id != ''):
            self.app_client = await self.viam_connect()

            message_params = { 'limit': 100, 'page_size': 1000}
            current_time = datetime.now(pytz.utc)
            start_time = current_time - timedelta(hours=1)

            while self.run_loop:
                message_params['date_sent_after'] = start_time
                start_time = datetime.now(pytz.utc)
                messages = self.twilio_client.messages.list(**message_params)
                for record in messages:
                    sent =  ""
                    if record.date_sent:
                        sent = record.date_sent.strftime("%d/%m/%Y %H:%M:%S")

                    message = {'body': record.body, 'to': record.to, 'from': record.from_, 'sent': sent }
                    print(message)

                    format_time = datetime.strptime(message['sent'], '%d/%m/%Y %H:%M:%S')
                    await self.app_client.data_client.tabular_data_capture_upload(tabular_data=[{"readings": message}], part_id=self.part_id, 
                                                                            component_type="rdk:component:sensor", component_name=self.name,
                                                                            method_name="Readings", tags=["sms_message"],
                                                                            data_request_times=[(format_time, format_time)])
                await asyncio.sleep(2)
        else:
            LOGGER.error("app_api_key and app_api_key_id must be configured to enable store_log_in_data_management")

    async def do_command(
                self,
                command: Mapping[str, ValueTypes],
                *,
                timeout: Optional[float] = None,
                **kwargs
            ) -> Mapping[str, ValueTypes]:
        result = {}

        if 'command' in command:
            if command['command'] == 'send':

                message_args = {}
                media_asset = {}

                if self.enforce_preset and not "preset" in command:
                    return "preset message must be specified"

                if "preset" in command:
                    message_args['body'] = self.preset_messages[command['preset']]

                # if local media, create as a twilio asset first
                if (('media_path' in command) or ('media_base64' in command)) and (self.twilio_media_sid != ""):
                    media_uuid = str(uuid.uuid4())
                    if 'media_path' in command:
                        file_name = f"{media_uuid}-{Path(command['media_path']).name}"
                        file_contents = open(command['media_path'], 'rb')
                        mime_type = mimetypes.guess_type(command['media_path'])[0]
                    else:
                        file_name = f"{media_uuid}-media"
                        file_contents = BytesIO(base64.b64decode(command['media_base64']))
                        mime_type = command['media_mime_type']
                        
                    asset = self.twilio_client.serverless.v1.services(self.twilio_media_sid).assets.create(friendly_name=file_name)

                    media_asset['asset_sid'] = asset.sid

                    # the twilio SDK does not have a method for actually uploading the media content so need to use the API directly
                    service_url = f'https://serverless-upload.twilio.com/v1/Services/{self.twilio_media_sid}'
                    upload_url = f'{service_url}/Assets/{asset.sid}/Versions'

                    # Create a new Asset Version
                    version_args = { "url": upload_url,
                                     "auth": (self.twilio_account_sid, self.twilio_auth_token),
                                     "files": {
                                        'Content': (file_name, file_contents, mime_type)
                                    },
                                    "data": {
                                        'Path': file_name,
                                    'Visibility': 'protected',
                                    }
                    }
                    response = requests.post(**version_args)
                    new_version_sid = json.loads(response.text).get("sid")

                    # create a build
                    build = self.twilio_client.serverless.v1.services(self.twilio_media_sid).builds.create(
                        asset_versions=[new_version_sid],
                    )
                    build_sid = build.sid

                    # wait for build to complete
                    build_status = ""
                    while build_status != "completed":
                        build_status = (
                            self.twilio_client.serverless.v1.services(self.twilio_media_sid)
                            .builds(build_sid)
                            .build_status()
                            .fetch()
                        )
                        await asyncio.sleep(.2)
                        build_status = build_status.status

                    media_asset['build_sid'] = build_sid

                    environment = self.twilio_client.serverless.v1.services(self.twilio_media_sid).environments.create(
                        unique_name=media_uuid, domain_suffix=media_uuid[:15]
                    )

                    media_asset['environment_sid'] = environment.sid

                    # deploy the build
                    deployment = (
                        self.twilio_client.serverless.v1.services(self.twilio_media_sid)
                        .environments(environment.sid)
                        .deployments.create(build_sid=build_sid)
                    )
                    
                    media_asset['deployment_sid'] = deployment.sid

                    message_args['media_url'] = f"https://{environment.domain_name}/{file_name}" 
                elif 'media_url' in command:
                     message_args['media_url'] = command['media_url']

                if 'from' in command:
                    message_args['from_'] = command['from']
                else:
                    message_args['from_'] = self.default_from
                message_args['to'] = command['to']
                if not "preset" in command:
                    message_args['body'] = command['body'] or ""

                message = self.twilio_client.messages.create(**message_args)

                if message.error_message != None:
                    result['status'] = 'error'
                    result['error'] = message.error_message
                else:
                    result['status'] = 'sent'

                # clean up if media was sent

                if 'deployment_sid' in media_asset:
                    # the following seems like a hack, but appears to be the only way to delete the deployment
                    deployment = (
                        self.twilio_client.serverless.v1.services(self.twilio_media_sid)
                        .environments(media_asset['environment_sid'])
                        .deployments.create()
                    )
                    self.twilio_client.serverless.v1.services(self.twilio_media_sid).environments(
                        media_asset['environment_sid']
                    ).delete()
                if 'build_sid' in media_asset:
                    self.twilio_client.serverless.v1.services(self.twilio_media_sid).builds(
                        media_asset['build_sid']
                    ).delete()
                if 'asset_sid' in media_asset:
                    self.twilio_client.serverless.v1.services(self.twilio_media_sid).assets(
                        media_asset['asset_sid']
                    ).delete()

            elif command['command'] == 'get':
                result = await self.get(command)
        else:
            result['status'] = 'error'
            result['error'] = 'command is required'
        return result  
    
    async def get(self, command):
        result = {}
        number = 5
        if 'number' in command:
            number = command['number']

        if self.store_log_in_data_management:
            query = []
            match = {"component_name": self.name}
            if "from" in command:
                match["data.readings.from"] = { "$eq": command["from"] }
            if "to" in command:
                match["data.readings.to"] = { "$eq": command["to"] }
            expr = {}
            if "time_start" in command:
                expr["$gte"] = [ "$time_received", { "$toDate": datetime.strptime(command['time_start'], "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S.000Z") }]
            if "time_end" in command:
                expr["$lte"] = [ "$time_received", { "$toDate": datetime.strptime(command['time_end'], "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S.000Z") }]
            if len(expr):
                match["$expr"] = expr
            query.append(bson.encode({"$match": match }))
            query.append(bson.encode({"$sort": { "time_received": -1 } }))
            query.append(bson.encode({ "$limit": number }))
            tabular_data = await self.app_client.data_client.tabular_data_by_mql(organization_id=self.organization_id, mql_binary=query)
            result['messages'] = []
            for tabular in tabular_data:
                sent = ""
                sent = tabular['time_received'].strftime("%d/%m/%Y %H:%M:%S")
                data = tabular["data"]["readings"]
                result['messages'].append({'body': data["body"], 'to': data["to"], 'from': data["from"], 'sent': sent })
            result['status'] = 'retrieved'
        else:
            message_params = {'limit':number, 'page_size':1000}
            if 'from' in command:
                message_params['from_'] = command['from']
            if 'to' in command:
                message_params['to'] = command['to']
            if 'time_start' in command:
                message_params['date_sent_after'] = datetime.strptime(command['time_start'], '%d/%m/%Y %H:%M:%S')
            if 'time_end' in command:
                message_params['date_sent_before'] = datetime.strptime(command['time_end'], '%d/%m/%Y %H:%M:%S')
            messages = self.twilio_client.messages.list(**message_params)
            result['messages'] = []
            for record in messages:
                sent =  ""
                if record.date_sent:
                    sent = record.date_sent.strftime("%d/%m/%Y %H:%M:%S")
                result['messages'].append({'body': record.body, 'to': record.to, 'from': record.from_, 'sent': sent })
            result['status'] = 'retrieved'
        
        return result