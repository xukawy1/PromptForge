from collections import defaultdict
from typing import Callable


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable):
        self._listeners[event_name].append(callback)

    def publish(self, event_name: str, payload=None):
        for callback in list(self._listeners.get(event_name, [])):
            callback(payload)

    def unsubscribe(self, event_name: str, callback: Callable):
        if callback in self._listeners.get(event_name, []):
            self._listeners[event_name].remove(callback)
