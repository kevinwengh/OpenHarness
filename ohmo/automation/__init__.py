"""Ohmo-specific automation workflow composition."""

from ohmo.automation.actions import ChannelSendAction, KnowledgeUpsertAction
from ohmo.automation.agent import RuntimeSkillAgentExecutor
from ohmo.automation.events import channel_message_event
from ohmo.automation.service import AutomationDispatch, OhmoAutomationService

__all__ = [
    "AutomationDispatch",
    "ChannelSendAction",
    "KnowledgeUpsertAction",
    "OhmoAutomationService",
    "RuntimeSkillAgentExecutor",
    "channel_message_event",
]
