"""OAuth support services shared by authentication integrations.

Provider-specific flows own credential meaning while this package owns reusable
protocol mechanics. Imports must not initiate login, bind sockets, or expose
tokens; asynchronous resources belong to the calling auth lifecycle.
"""
