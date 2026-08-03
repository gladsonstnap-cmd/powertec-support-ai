"""Deterministic, in-memory storage for diagnostic memory."""

from copy import deepcopy
from dataclasses import replace
from typing import Mapping

from app.services.diagnostic_engine.memory_models import MemoryEntry, MemoryFact, MemoryQueryResult, MemorySnapshot
from app.services.diagnostic_engine.memory_policy import DiagnosticMemoryPolicy


class DiagnosticMemoryEngine:
    """Store and query diagnostic memory according to a fixed policy."""

    def __init__(
        self,
        policy: DiagnosticMemoryPolicy | None = None,
        initial_snapshot: MemorySnapshot | None = None,
    ) -> None:
        self.policy = policy or DiagnosticMemoryPolicy()
        snapshot = MemorySnapshot() if initial_snapshot is None else initial_snapshot
        if not isinstance(snapshot, MemorySnapshot):
            raise TypeError("initial_snapshot must be a MemorySnapshot")
        self._entries: list[MemoryEntry] = []
        for entry in snapshot.entries[-self.policy.max_entries :]:
            self._entries.append(self._prepare_entry(entry))
        self._known_information = self._limited_mapping(snapshot.known_information)
        self._metadata = deepcopy(snapshot.metadata) if self.policy.preserve_metadata else {}

    def add_entry(
        self,
        entry: MemoryEntry,
        *,
        known_information: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MemorySnapshot:
        if not isinstance(entry, MemoryEntry):
            raise TypeError("entry must be a MemoryEntry")
        prepared = self._prepare_entry(entry)
        self._entries.append(prepared)
        self._entries = self._entries[-self.policy.max_entries :]
        if known_information is not None:
            self._update_known_information(known_information)
        if metadata is not None and self.policy.preserve_metadata:
            self._metadata.update(deepcopy(dict(metadata)))
        return self.snapshot()

    def query(
        self,
        *,
        key: str | None = None,
        category: str | None = None,
        source: str | None = None,
        minimum_confidence: float | None = None,
        limit: int | None = None,
    ) -> MemoryQueryResult:
        threshold = self.policy.minimum_fact_confidence if minimum_confidence is None else minimum_confidence
        if not isinstance(threshold, int | float) or isinstance(threshold, bool) or not 0.0 <= threshold <= 1.0:
            raise ValueError("minimum_confidence must be a number between 0.0 and 1.0")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
            raise ValueError("limit must be a positive integer")
        effective_limit = min(limit or self.policy.max_query_results, self.policy.max_query_results)
        matches = tuple(
            fact
            for entry in self._entries
            for fact in entry.facts
            if fact.confidence >= threshold
            and (key is None or fact.key == key)
            and (category is None or fact.category == category)
            and (source is None or fact.source == source)
        )
        return MemoryQueryResult(matches=matches[:effective_limit], total=len(matches), truncated=len(matches) > effective_limit)

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(tuple(self._entries), self._known_information, self._metadata)

    def known_information(self) -> dict[str, object]:
        return deepcopy(self._known_information)

    def entries(self) -> tuple[MemoryEntry, ...]:
        return tuple(deepcopy(self._entries))

    def clear(self) -> None:
        self._entries.clear()
        self._known_information.clear()
        self._metadata.clear()

    def __repr__(self) -> str:
        return f"DiagnosticMemoryEngine(entries={len(self._entries)}, policy={self.policy!r})"

    def _prepare_entry(self, entry: MemoryEntry) -> MemoryEntry:
        facts = [fact for fact in deepcopy(entry.facts) if fact.confidence >= self.policy.minimum_fact_confidence]
        if self.policy.merge_duplicate_facts and self.policy.prefer_higher_confidence_fact:
            facts = self._merge_facts(facts)
        facts = facts[: self.policy.max_facts_per_entry]
        return replace(
            entry,
            facts=tuple(facts),
            hypotheses=entry.hypotheses if self.policy.retain_hypotheses else (),
            evidences=entry.evidences if self.policy.retain_evidences else (),
            questions=entry.questions if self.policy.retain_questions else (),
            answers=entry.answers if self.policy.retain_answers else (),
        )

    def _merge_facts(self, facts: list[MemoryFact]) -> list[MemoryFact]:
        accepted: list[MemoryFact] = []
        for fact in facts:
            location = self._duplicate_location(fact, accepted)
            if location is None:
                accepted.append(fact)
                continue
            entry_index, fact_index = location
            existing = accepted[fact_index] if entry_index is None else self._entries[entry_index].facts[fact_index]
            if fact.confidence <= existing.confidence:
                continue
            if entry_index is None:
                accepted[fact_index] = fact
            else:
                stored = list(self._entries[entry_index].facts)
                stored[fact_index] = fact
                self._entries[entry_index] = replace(self._entries[entry_index], facts=tuple(stored))
        return accepted

    def _duplicate_location(self, fact: MemoryFact, accepted: list[MemoryFact]) -> tuple[int | None, int] | None:
        for index, existing in enumerate(accepted):
            if self._equivalent(existing, fact):
                return None, index
        for entry_index, entry in enumerate(self._entries):
            for fact_index, existing in enumerate(entry.facts):
                if self._equivalent(existing, fact):
                    return entry_index, fact_index
        return None

    def _equivalent(self, left: MemoryFact, right: MemoryFact) -> bool:
        return (
            left.category == right.category
            and left.key == right.key
            and left.source == right.source
            and self._stable_value(left.value) == self._stable_value(right.value)
            and abs(left.confidence - right.confidence) <= self.policy.duplicate_confidence_tolerance
        )

    def _update_known_information(self, values: Mapping[str, object]) -> None:
        for key, value in deepcopy(dict(values)).items():
            if key in self._known_information or len(self._known_information) < self.policy.max_known_information_items:
                self._known_information[key] = value

    def _limited_mapping(self, values: Mapping[str, object]) -> dict[str, object]:
        return dict(list(deepcopy(dict(values)).items())[: self.policy.max_known_information_items])

    @classmethod
    def _stable_value(cls, value: object) -> object:
        if isinstance(value, dict):
            return tuple(sorted((str(key), cls._stable_value(item)) for key, item in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(cls._stable_value(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted((repr(cls._stable_value(item)) for item in value)))
        return value
