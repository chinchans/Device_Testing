import os
from typing import Any, Dict, Optional
from zcatalyst_sdk._constants import CATALYST_RESOURCE_ID, X_CATALYST_RESOURCE_ID
from zcatalyst_sdk import validator
from zcatalyst_sdk.exceptions import CatalystDataStreamError
from ..types import Component
from ..types.datastreams import (
    ChannelIdentifier,
    UserIdentifier,
    GetAllChannelsResponse,
    GetChannelResponse,
    ChannelLiveCountResponse,
    PublishDataResponse,
    TokenResponse,
    DataStreamsConfig,
    MessageType,
    ConnectionState,
    CustomEvent,
    DataStreamMessageEvent
)
from .._http_client import AuthorizedHttpClient
from .._constants import (
    RequestMethod,
    CredentialUser,
    Components,
    CatalystService
)
from .websocket_client import DataStreamsWebSocket

__all__ = [
    'Datastreams',
    'DataStreamsWebSocket',
    'DataStreamsConfig',
    'MessageType',
    'ConnectionState',
    'CustomEvent',
    'DataStreamMessageEvent'
]

class Datastreams(Component):
    """
    A class to handle Catalyst Datastreams operations.

    This class provides methods to interact with Catalyst Datastreams service,
    including getting channel information, publishing data, and retrieving live counts.
    """

    def __init__(self, app) -> None:
        """
        Initialize the Datastreams component.

        Args:
            app: The Catalyst application instance.
        """
        self._app = app
        self._requester = AuthorizedHttpClient(self._app)

    def get_component_name(self) -> str:
        """
        Get the component name for this service.

        Returns:
            str: The component name 'Datastreams'.
        """
        return Components.DATASTREAMS

    def get_all_channels(self) -> GetAllChannelsResponse:
        """
        Retrieve all datastream channels.

        This method fetches all available datastream channels from the Catalyst service.

        Returns:
            GetAllChannelsResponse: Response containing all datastream channels information.

        Raises:
            CatalystDataStreamError: If the request fails or returns an error.

        Example:
            >>> datastream = app.datastream()
            >>> res = datastream.get_all_channels()
            >>> print('channels::', res)
        """
        resp = self._requester.request(
            method=RequestMethod.GET,
            path='/datastreams/channel',
            user=CredentialUser.ADMIN,
            catalyst_service=CatalystService.SERVERLESS
        )
        return resp.response_json.get('data')

    def get_channel_details(self, channel_id: ChannelIdentifier) -> GetChannelResponse:
        """
        Retrieve details of a specific datastream channel.

        This method fetches detailed information about a specific datastream channel
        identified by the provided channel ID or name.

        Args:
            channel_id (ChannelIdentifier): The unique identifier or name of the datastream channel.
                                          Must be a non-empty string or number.

        Returns:
            GetChannelResponse: Response containing the channel details.

        Raises:
            CatalystDataStreamError: If channel_id is invalid or the request fails.

        Example:
            >>> datastream = app.datastream()
            >>> channel_details = datastream.get_channel_details("12345")  # Using ID
            >>> # or
            >>> channel_details = datastream.get_channel_details("my_channel")  # Using name
            >>> print('channel details::', channel_details)
        """
        validator.is_non_empty_string_or_number(channel_id, 'channel_id', CatalystDataStreamError)
        resp = self._requester.request(
            method=RequestMethod.GET,
            path=f'/datastreams/channel/{channel_id}',
            user=CredentialUser.ADMIN,
            catalyst_service=CatalystService.SERVERLESS
        )
        return resp.response_json.get("data")

    def get_live_count(self, channel_id: ChannelIdentifier) -> ChannelLiveCountResponse:
        """
        Get the live connection count for a specific datastream channel.

        This method retrieves the number of active connections currently
        subscribed to the specified datastream channel.

        Args:
            channel_id (ChannelIdentifier): The unique identifier or name of the datastream channel.
                                          Must be a non-empty string or number.

        Returns:
            ChannelLiveCountResponse: Response containing the live connection count information.

        Raises:
            CatalystDataStreamError: If channel_id is invalid or the request fails.

        Example:
            >>> datastream = app.datastream()
            >>> live_count = datastream.get_live_count("12345")  # Using ID
            >>> # or
            >>> live_count = datastream.get_live_count("my_channel")  # Using name
            >>> print('live count::', live_count)
        """
        validator.is_non_empty_string_or_number(channel_id, 'channel_id', CatalystDataStreamError)
        resp = self._requester.request(
            method=RequestMethod.GET,
            path=f'/datastreams/channel/{channel_id}/liveclient',
            user=CredentialUser.ADMIN,
            catalyst_service=CatalystService.SERVERLESS
        )
        return resp.response_json.get("data")

    def publish_data(self, channel_id: ChannelIdentifier, data: str) -> PublishDataResponse:
        """
        Publish data to a specific datastream channel.

        This method sends data to the specified datastream channel, which will be
        broadcasted to all active subscribers of that channel.

        Args:
            channel_id (ChannelIdentifier): The unique identifier or name of the datastream channel.
                                          Must be a non-empty string or number.
            data (str): The data to be published to the channel.
                       Must be a non-empty string.

        Returns:
            PublishDataResponse: Response containing the publish operation result.

        Raises:
            CatalystDataStreamError: If channel_id or data is invalid, or the request fails.

        Example:
            >>> datastream = app.datastream()
            >>> result = datastream.publish_data("12345", "Hello, subscribers!")  # Using ID
            >>> # or
            >>> result = datastream.publish_data("my_channel", "Hello, subscribers!")  # Using name
            >>> print('publish result::', result)
        """
        validator.is_non_empty_string_or_number(channel_id, 'channel_id', CatalystDataStreamError)
        validator.is_non_empty_string(data, 'data', CatalystDataStreamError)
        resp = self._requester.request(
            method=RequestMethod.POST,
            path=f'/datastreams/channel/{channel_id}/stream',
            json={"data": data},
            user=CredentialUser.ADMIN,
            catalyst_service=CatalystService.SERVERLESS
        )
        return resp.response_json.get("data")

    def get_token_pair(
        self,
        channel_id: str,
        user_id: Optional[UserIdentifier] = None,
        connection_name: Optional[str] = None
    ) -> TokenResponse:
        """
        Get a token pair for a specific datastream channel.

        This method retrieves a token pair that can be used to authenticate
        and authorize access to the specified datastream channel.

        Args:
            channel_id (str): The unique identifier or name of the datastream channel.
                                          Must be a non-empty string.
            user_id (Optional[UserIdentifier]): The user identifier, can be a user ID
                        (string or number).Mutually exclusive with connection_name.
            connection_name (Optional[str]): The connection name (string).
                                          Mutually exclusive with user_id.

        Returns:
            TokenResponse: Response containing the token pair information.

        Raises:
            CatalystDataStreamError: If channel_id is invalid, if user_id/connection_name is
                                    invalid, if neither user_id nor connection_name is
                                    provided, or if the request fails.

        Example:
            >>> datastream = app.datastream()
            >>> token_pair = datastream.get_token_pair("CHANNEL_ID", user_id="user123")
            >>> token_pair = datastream.get_token_pair("CHANNEL_ID", connection_name="sample")
            >>> print('token pair::', token_pair)
        """
        validator.is_non_empty_string(channel_id, 'channel_id', CatalystDataStreamError)
        payload = {}
        # user_id takes precedence over connection_name when both are given
        if user_id:
            validator.is_non_empty_string_or_number(user_id, 'user_id', CatalystDataStreamError)
            payload = {"app_user_id": user_id}
        elif connection_name:
            validator.is_non_empty_string(connection_name,
                                        'connection_name', CatalystDataStreamError)
            payload = {"connection_name": connection_name}
        else:
            validator.is_non_empty_dict(payload, 'user_id or connection_name',
                                CatalystDataStreamError)
        resp = self._requester.request(
            method=RequestMethod.POST,
            path=f'/datastreams/channel/{channel_id}/tokenpair',
            user=CredentialUser.USER,
            headers={
                CATALYST_RESOURCE_ID: os.getenv(X_CATALYST_RESOURCE_ID)
            },
            json=payload,
            catalyst_service=CatalystService.SERVERLESS
        )
        return resp.response_json.get("data")
