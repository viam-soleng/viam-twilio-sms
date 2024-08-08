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

from viam.services.generic import Generic
from viam.logging import getLogger

import uuid
import json
import requests
import mimetypes
from pathlib import Path
from datetime import datetime
from twilio.rest import Client

LOGGER = getLogger(__name__)

class twilioSMS(Generic, Reconfigurable):

    MODEL: ClassVar[Model] = Model(ModelFamily("mcvella", "messaging"), "twilio-sms")
    twilio_client: Client
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_media_sid: str
    default_from: str

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
        return

    # Handles attribute reconfiguration
    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        self.twilio_account_sid = config.attributes.fields["account_sid"].string_value
        self.twilio_auth_token = config.attributes.fields["auth_token"].string_value
        self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
        self.twilio_media_sid = config.attributes.fields["media_sid"].string_value or ""
        self.default_from = config.attributes.fields["default_from"].string_value or ""
        return
    
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
                # if media, create as a twilio asset first
                if 'media_path' in command and (self.twilio_media_sid != ""):
                    asset = self.twilio_client.serverless.v1.services(self.twilio_media_sid).assets.create(friendly_name=uuid.uuid4())

                    # the twilio SDK does not have a method for actually uploading the media content so need to use the API directly
                    service_url = f'https://serverless-upload.twilio.com/v1/Services/{self.twilio_media_sid}'
                    upload_url = f'{service_url}/Assets/{asset.sid}/Versions'

                    file_contents = open(command['media_path'], 'rb')
                    # Create a new Asset Version
                    version_args = { "url": upload_url,
                                     "auth": (self.twilio_account_sid, self.twilio_auth_token),
                                     "files": {
                                        'Content': (Path(command['media_path']).name, file_contents, mimetypes.guess_type(command['media_path'])[0])
                                    },
                                    "data": {
                                        'Path': Path(command['media_path']).name,
                                    'Visibility': 'protected',
                                    }
                    }
                    response = requests.post(**version_args)
                    new_version_sid = json.loads(response.text).get("sid")
                    message_args['media_url'] = [f'https://serverless.twilio.com/v1/Services/{self.twilio_media_sid}/Functions/{asset.sid}/Versions/{new_version_sid}']
                
                if 'from' in command:
                    message_args['from_'] = command['from']
                else:
                    message_args['from_'] = self.default_from
                message_args['to'] = command['to']
                message_args['body'] = command['body'] or ""

                message = self.twilio_client.messages.create(**message_args)

                if message.error_message != 0:
                    result['status'] = 'error'
                    result['error'] = message.error_message
                else:
                    result['status'] = 'sent'
            elif command['command'] == 'get':
                number = 5
                if 'number' in command:
                    number = command['number']

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
                    result['messages'].append({'body': record.body, 'to': record.to, 'from': record.from_, 'sent': record.date_sent.strftime("%d/%m/%Y %H:%M:%S") })
                result['status'] = 'retrieved'
        else:
            result['status'] = 'error'
            result['error'] = 'command is required'
        return result  