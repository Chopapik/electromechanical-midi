"""Stable internal expression associations and diagnostics-independent execution."""
import copy
from dataclasses import asdict, replace
import unittest

from playback.performance import PerformancePlan, ReinforcementEvent
from playback.planning_context import (ensure_extra_bindings, append_extra,
    extra_articulation, import_extra_articulation, replace_extras, set_extra_articulation)
from playback.fdd_legato import apply as legato
from runtime.arranger import arrange
from runtime.compiler import compile_plan
import test_fdd_legato as helpers


class ExtraBindingTests(unittest.TestCase):
    def plan(self):
        first = ReinforcementEvent('source', 'fdd-2', 0., .2, 130., 95)
        second = replace(first)
        return PerformancePlan('fixture', [], [{'id':'fdd-2', 'type':'FDD'}], {},
            reinforcements=[first, second], execution_articulation={
                'extra:0': {'kind':'first'}, 'extra:1': {'kind':'second'}})

    def test_equal_duplicates_have_distinct_ids_and_replacement_keeps_identity(self):
        plan = self.plan()
        before = ensure_extra_bindings(plan)
        self.assertEqual([b.identity for b in before], ['extra-event:0', 'extra-event:1'])
        self.assertEqual(asdict(before[0].event), asdict(before[1].event))
        second = replace(plan.reinforcements[1], hz=150.)
        replace_extras(plan, [(1, second)])
        self.assertEqual(plan.internal_context.extras[0].identity, 'extra-event:1')
        self.assertIs(plan.internal_context.extras[0].event, second)
        self.assertEqual(plan.execution_articulation, {'extra:0': {'kind':'second'}})
        self.assertEqual(compile_plan(plan).commands[0].articulation, {'kind':'second'})
        self.assertEqual(append_extra(plan, replace(second, start=1.), {'kind':'third'}), 'extra-event:2')
        self.assertEqual(extra_articulation(plan, 1), {'kind':'third'})
        self.assertNotIn('internal_context', plan.as_dict())

    def test_repeated_same_object_is_still_two_occurrences(self):
        plan = self.plan()
        plan.reinforcements[1] = plan.reinforcements[0]
        identities = [b.identity for b in ensure_extra_bindings(plan)]
        self.assertEqual(len(set(identities)), 2)
        replace_extras(plan, [(1, plan.reinforcements[1])])
        self.assertEqual(plan.internal_context.extras[0].identity, identities[1])
        self.assertEqual(extra_articulation(plan, 0), {'kind':'second'})

    def test_absent_sidecar_and_legacy_projection_import(self):
        plan = self.plan()
        ensure_extra_bindings(plan)
        set_extra_articulation(plan, 1, None)
        replace_extras(plan, [(1, plan.reinforcements[1])])
        self.assertEqual(plan.execution_articulation, {})
        self.assertIsNone(compile_plan(plan).commands[0].articulation)
        identity = plan.internal_context.extras[0].identity
        plan.execution_articulation = {'extra:0': {'kind':'legacy-producer'}}
        import_extra_articulation(plan)
        self.assertEqual(plan.internal_context.extras[0].identity, identity)
        self.assertEqual(extra_articulation(plan, 0), {'kind':'legacy-producer'})


class ContextExecutionTests(unittest.TestCase):
    setUp = helpers.LegatoTests.setUp
    source = helpers.LegatoTests.source
    registry = helpers.LegatoTests.registry

    def test_all_reports_can_be_removed_after_planning_without_execution_change(self):
        registry = self.registry()
        source = self.source([('Riff', 0, [(i*.3, i*.3+.1, 60+i%3) for i in range(12)])])
        plan = arrange(source, registry)
        expected = compile_plan(plan)
        plan.hardware.clear()
        plan.analysis.clear()
        plan.articulation.clear()
        plan.idle_report.clear()
        plan.strict_report.clear()
        self.assertEqual(compile_plan(plan), expected)

    def test_legato_groups_do_not_depend_on_expressive_diagnostic_report(self):
        registry = self.registry()
        registry.document['parameters']['arrangementPreset'] = 'fdd_expressive_solo'
        source = self.source([('Riff', 0, [(i*.3, i*.3+.1, 60+i%3) for i in range(12)])])
        original = arrange(source, registry)
        without_report = copy.deepcopy(original)
        without_report.hardware.pop('fddExpressive')
        legato(original, registry, source)
        legato(without_report, registry, source)
        self.assertEqual(compile_plan(original), compile_plan(without_report))
