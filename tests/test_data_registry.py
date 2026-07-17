"""Phase 2.1 (remediation) — the data-lifecycle registry mechanism.

These tests pin the enforcement guarantee behind Phase 2's definition of done:
registering a category with incomplete or inconsistent lifecycle metadata must
fail loudly. Concrete-category coverage arrives with chunk 2.1b.
"""

import unittest
from pathlib import Path

import data_registry as dr


def make_category(**overrides):
    """A fully-valid category; override one field to test a failure."""
    defaults = dict(
        id="drafts",
        label="Draft JSON",
        owner="python",
        sensitivity="personal",
        paths=lambda: [Path("/tmp/drafts.json")],
        retention="Kept until the user clears conversations.",
        wipe_modes=frozenset(dr.WIPE_MODES),  # all three (valid nesting)
        included_in_report=True,
        included_in_export=True,
        may_contain_user_text=True,
        size=lambda: 0,
        wipe=lambda: dr.WipeResult(ok=True),
        verify=lambda: dr.VerificationResult(ok=True),
    )
    defaults.update(overrides)
    return dr.DataCategory(**defaults)


class ValidationTests(unittest.TestCase):
    def test_valid_category_passes(self):
        dr.validate_category(make_category())  # must not raise

    def test_blank_id_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(id="  "))

    def test_blank_label_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(label=""))

    def test_unknown_owner_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(owner="rust"))

    def test_unknown_sensitivity_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(sensitivity="secret"))

    def test_blank_retention_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(retention=""))

    def test_unknown_wipe_mode_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(wipe_modes=frozenset({"nuke"})))

    def test_mode_nesting_violation_rejected(self):
        # In conversations but NOT in the outer modes that must contain it.
        with self.assertRaises(ValueError):
            dr.validate_category(
                make_category(wipe_modes=frozenset({dr.WIPE_MODE_CONVERSATIONS}))
            )

    def test_factory_reset_only_is_valid(self):
        # A category wiped only by factory reset is fine (no inner-mode implied).
        dr.validate_category(
            make_category(wipe_modes=frozenset({dr.WIPE_MODE_FACTORY_RESET}))
        )

    def test_empty_wipe_modes_is_valid(self):
        # A store intentionally never wiped (e.g. opt-in downloaded models).
        dr.validate_category(make_category(wipe_modes=frozenset()))

    def test_non_callable_paths_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(paths=[Path("/tmp/x")]))

    def test_non_bool_flag_rejected(self):
        with self.assertRaises(ValueError):
            dr.validate_category(make_category(included_in_report="yes"))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = dr.DataRegistry()

    def test_register_and_lookup(self):
        cat = self.reg.register(make_category(id="recordings", label="Raw recordings"))
        self.assertIs(self.reg.get("recordings"), cat)
        self.assertEqual(self.reg.ids(), ["recordings"])
        self.assertEqual(len(self.reg), 1)

    def test_duplicate_id_rejected(self):
        self.reg.register(make_category(id="dup"))
        with self.assertRaises(ValueError):
            self.reg.register(make_category(id="dup"))

    def test_register_validates(self):
        with self.assertRaises(ValueError):
            self.reg.register(make_category(owner="rust"))

    def test_in_mode_filters(self):
        self.reg.register(
            make_category(id="conv", wipe_modes=frozenset(dr.WIPE_MODES))
        )
        self.reg.register(
            make_category(id="factory_only",
                          wipe_modes=frozenset({dr.WIPE_MODE_FACTORY_RESET}))
        )
        conv = [c.id for c in self.reg.in_mode(dr.WIPE_MODE_CONVERSATIONS)]
        factory = [c.id for c in self.reg.in_mode(dr.WIPE_MODE_FACTORY_RESET)]
        self.assertEqual(conv, ["conv"])
        self.assertCountEqual(factory, ["conv", "factory_only"])

    def test_in_mode_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.in_mode("nuke")

    def test_module_registry_is_a_registry(self):
        self.assertIsInstance(dr.REGISTRY, dr.DataRegistry)


if __name__ == "__main__":
    unittest.main()
