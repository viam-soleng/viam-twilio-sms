"""
This file registers the model with the Python SDK.
"""

from viam.services.generic import Generic
from viam.resource.registry import Registry, ResourceCreatorRegistration

from .twilioSMS import twilioSMS

Registry.register_resource_creator(Generic.SUBTYPE, twilioSMS.MODEL, ResourceCreatorRegistration(twilioSMS.new, twilioSMS.validate))
