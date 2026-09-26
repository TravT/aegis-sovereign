"""
Model Context Protocol (MCP) Server for Aegis Sovereign Knowledge Appliance.
Standard JSON-RPC 2.0 stdio server for Antigravity, Claude, and AI Agent environments.
"""

from .server import SovereignMCPServer, main

__all__ = [
    "SovereignMCPServer",
    "main",
]
