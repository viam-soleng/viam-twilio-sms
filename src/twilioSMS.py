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

import time
import asyncio
from datetime import datetime
from twilio.rest import Client

LOGGER = getLogger(__name__)

class twilioSMS(Generic, Reconfigurable):

    MODEL: ClassVar[Model] = Model(ModelFamily("mcvella", "messaging"), "twilio-sms")
    twilio_client: Client
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
        account_sid = config.attributes.fields["account_sid"].string_value
        auth_token = config.attributes.fields["auth_token"].string_value
        self.twilio_client = Client(account_sid, auth_token)
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
                if 'from' in command:
                    message_from = command['from']
                else:
                    message_from = self.default_from
                message_to = command['to']
                message_body = command['body']
                message = self.twilio_client.messages.create(
                    from_=message_from,
                    to=message_to,
                    body=message_body
                )
                if message.error_message != "":
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