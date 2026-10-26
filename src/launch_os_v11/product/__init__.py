"""Owner-facing Launch Room.

The product surface is a room, not a chat transcript. Model text produced here
comes from the local synthetic script adapter and is not evidence of live
model intelligence.
"""

from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.projection import LaunchRoomView
from launch_os_v11.product.room import LaunchRoomService

__all__ = ["LaunchRoomService", "LaunchRoomView", "ProductError"]
