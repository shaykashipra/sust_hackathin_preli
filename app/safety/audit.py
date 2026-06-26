from dataclasses import dataclass, field


@dataclass
class SafetyAudit:
    events: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def add(self, event: str) -> None:
        self.events.append(event)

    def set_check(self, name: str, passed: bool) -> None:
        self.checks[name] = passed

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) if self.checks else True
