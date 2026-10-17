class PluginError(Exception):
    """A plugin is broken, incompatible or misconfigured."""


class PluginLoadError(PluginError):
    """One or more enabled plugins can't load. ``problems`` holds one message per problem."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(problems))
