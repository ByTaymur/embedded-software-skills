"""Fictional CMSIS-SVD data, policy and entry point tests; no hardware evidence."""
import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool import core, mcp_server, svd
from embedded_ai_tool.cli import parser, run, serve_request
from embedded_ai_tool.core import Profile
from embedded_ai_tool.live import Session
from test_live import GPIO, UID_ADDRESS, LiveCase

FIXTURE = Path(__file__).parent / "fixtures" / "svd" / "fictional.svd"


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.device = svd.Device.load(FIXTURE)

    def load_xml(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.svd"
            path.write_bytes(xml if isinstance(xml, bytes) else xml.encode())
            return svd.Device.load(path)

    def test_register_chains_and_defaults(self):
        d = self.device
        self.assertEqual(d.peripherals(), ["PORT", "OTHER", "NEXT", "FINAL"])
        r = d.lookup("port.third")
        self.assertEqual((r.address, r.size, r.reset_value, r.reset_mask, r.access),
                         (GPIO + 8, 16, 5, 0xffffffff, "read-write"))
        self.assertEqual(len(d.registers("FINAL")), len(d.registers("PORT")) + 1)
        self.assertEqual(d.lookup("FINAL.EXTRA").address, GPIO + 0x3200)
        # A peripheral override applies to registers that have no own default.
        self.assertEqual(d.lookup("OTHER.DATA0").size, 16)
        self.assertEqual(d.lookup("OTHER.DATA0").reset_value, 7)

    def test_arrays_clusters_and_aliases(self):
        d = self.device
        self.assertIs(d.lookup("PORT.DATA0"), d.lookup("port.data[0]"))
        self.assertEqual(d.lookup("PORT.LETTERD").address, GPIO + 44)
        self.assertEqual(d.lookup("PORT.ITEMC").address, GPIO + 56)
        r = d.lookup("PORT.GROUP[1].INNER1.VALUE")
        self.assertEqual((r.address, r.size, r.reset_mask), (GPIO + 206, 16, 65535))
        self.assertEqual(d.lookup("PORT.CHAIN.INNER1.VALUE").address, GPIO + 334)
        self.assertEqual(d.lookup("PORT.MODE.FLAG[1]").offset, 7)

    def test_bit_positions_and_enum_chains(self):
        d = self.device
        for value, name in enumerate(["ZERO", "ONE", "TWO", "THREE", "OTHER"]):
            fields = d.decode(d.lookup("PORT.MODE"), value | (value << 3) | (value << 8))
            self.assertEqual([f["enum_name"] for f in fields if f["name"] in {"STATE", "COPY", "LAST"}],
                             [name] * 3)
        self.assertEqual(d.lookup("PORT.MODE.COPY").width, 3)
        self.assertEqual(d.lookup("PORT.MODE.LAST").offset, 8)
        self.assertIs(d.lookup("PORT.MODE.STATE").register, d.lookup("PORT.MODE"))

    def test_missing_names_offer_suggestions(self):
        with self.assertRaisesRegex(ValueError, "yakın adlar: .*port.mode"):
            self.device.lookup("PORT.MOE")
        with self.assertRaisesRegex(ValueError, "yakın adlar"):
            self.device.registers("PRT")

    def test_cycles_and_missing_references(self):
        for nodes in (
            '<peripheral derivedFrom="B"><name>A</name></peripheral><peripheral derivedFrom="A"><name>B</name></peripheral>',
            '<peripheral><name>P</name><baseAddress>0</baseAddress><registers><register derivedFrom="B"><name>A</name></register><register derivedFrom="A"><name>B</name></register></registers></peripheral>',
            '<peripheral><name>P</name><baseAddress>0</baseAddress><registers><cluster derivedFrom="B"><name>A</name></cluster><cluster derivedFrom="A"><name>B</name></cluster></registers></peripheral>',
        ):
            with self.subTest(nodes=nodes), self.assertRaisesRegex(ValueError, "döngüsü"):
                self.load_xml(f"<device><peripherals>{nodes}</peripherals></device>")
        with self.assertRaisesRegex(ValueError, "bulunamadı"):
            self.load_xml('<device><peripherals><peripheral derivedFrom="NO"><name>A</name></peripheral></peripherals></device>')

    def test_untrusted_xml_and_size_limit(self):
        for xml in ('<!DOCTYPE device [<!ENTITY x "data">]><device/>', '<!DOCTYPE device><device/>'):
            for encoding in ("utf-8", "utf-16", "utf-32"):
                with self.subTest(encoding=encoding), self.assertRaisesRegex(ValueError, "DOCTYPE/ENTITY"):
                    self.load_xml(xml.encode(encoding))
        with patch.object(svd, "MAX_BYTES", 8), self.assertRaisesRegex(ValueError, "64 MB"):
            svd.Device.load(FIXTURE)

    def test_invalid_xml_dim_and_field(self):
        for xml in ("<device>", FIXTURE.read_text().replace("<dimIndex>A-D</dimIndex>", "<dimIndex>A-B</dimIndex>"),
                    FIXTURE.read_text().replace("[10:8]", "[40:8]")):
            with self.subTest(xml=xml[:30]), self.assertRaises(ValueError):
                self.load_xml(xml)

    def test_read_write_enum_usage_and_unknown_elements(self):
        xml = FIXTURE.read_text().replace("<usage>read</usage>", "<usage>read-write</usage>")
        d = self.load_xml(xml.replace("<size>32</size>", "<unknown>ignored</unknown><size>32</size>"))
        self.assertEqual(d.decode(d.lookup("PORT.MODE"), 1)[0]["enum_name"], "ONE")

    def test_inherited_children_can_be_referenced_in_derived_scope(self):
        xml = FIXTURE.read_text().replace('<register><name>EXTRA</name>',
                                         '<register derivedFrom="NEXT.MODE"><name>EXTRA</name>')
        d = self.load_xml(xml)
        self.assertEqual(d.lookup("FINAL.EXTRA").fields[0].name, "STATE")

    def test_mixed_array_aliases(self):
        xml = FIXTURE.read_text().replace('<name>INNER%s</name>', '<name>INNER[%s]</name>')
        d = self.load_xml(xml)
        self.assertIs(d.lookup("PORT.GROUP[1].INNER0.VALUE"), d.lookup("PORT.GROUP1.INNER[0].VALUE"))


class RegisterTests(LiveCase):
    def setUp(self):
        super().setUp()
        shutil.copy(FIXTURE, self.root / "input.svd")
        self.edit(lambda d: d["live"].update(svd="input.svd"))

    def args(self, *argv):
        return parser().parse_args(["--profile", str(self.path), "--session-dir", str(self.root / "s"), *argv])

    def test_listing_is_offline_and_filtered(self):
        with patch.object(core, "RPC", side_effect=AssertionError("connected")):
            result = run(self.args("reg", "list", "PORT", "--filter", "letter"))
        self.assertEqual(len(result["registers"]), 4)

    def test_one_guarded_request_per_register(self):
        self.rpc.put(GPIO, 32, 2)
        with patch.object(core, "RPC", return_value=self.rpc):
            result = run(self.args("reg", "read", "PORT.MODE", "PORT.MODE.STATE", "PORT.SECOND"))
        self.assertEqual(len(self.rpc.scripts), 2)
        self.assertEqual(result["registers"][0]["fields"][0]["enum_name"], "TWO")
        self.rpc.mem[UID_ADDRESS] = 0
        with patch.object(core, "RPC", return_value=self.rpc), self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            run(self.args("reg", "read", "PORT.MODE"))

    def test_svd_never_grants_permission(self):
        for name in ("OUTSIDE", "HAZARD", "FIELD_HAZARD"):
            with self.subTest(name=name), patch.object(core, "RPC", side_effect=AssertionError("connected")), \
                    self.assertRaisesRegex(ValueError, "Okuma izni yok"):
                run(self.args("reg", "read", f"PORT.{name}"))

    def test_all_read_actions_are_refused_on_registers_and_fields(self):
        path = self.root / "input.svd"
        original = path.read_text()
        for action in svd.SIDE_EFFECTS:
            path.write_text(original.replace("clear", action).replace("modifyExternal", action))
            for name in ("HAZARD", "FIELD_HAZARD"):
                with self.subTest(action=action, name=name), self.assertRaisesRegex(ValueError, "yan etkili"):
                    run(self.args("reg", "read", f"PORT.{name}"))

    def test_profile_protection_and_side_effects(self):
        for key in ("protected_ranges", "side_effect_ranges"):
            self.edit(lambda d, k=key: d["live"].update({k: [{"address": GPIO, "size": 4}]}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Okuma izni yok"):
                run(self.args("reg", "read", "PORT.MODE"))
            self.edit(lambda d, k=key: d["live"].update({k: []}))

    def test_endian_mismatch_and_optional_svd(self):
        self.edit(lambda d: d.update(byte_order="big"))
        profile = Profile(self.path)  # SVD is parsed on first use, not at profile load
        with self.assertRaisesRegex(ValueError, "byte order"):
            profile.svd()
        self.edit(lambda d: d["live"].pop("svd"))
        with self.assertRaisesRegex(ValueError, "live.svd"):
            run(self.args("reg", "list"))

    def test_serve_and_mcp_paths(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        session = Session(Profile(self.path), self.openocd(self.rpc))
        result = serve_request(json.dumps({"argv": ["reg", "read", "PORT.MODE"]}), base, session)
        self.assertTrue(result["ok"], result)
        bridge = mcp_server.Bridge(base, Profile(self.path), io.StringIO())
        with patch.object(core, "RPC", side_effect=AssertionError("connected")):
            listing = bridge.call("list_registers", {"peripheral": "PORT", "filter": "MODE"})
        self.assertFalse(listing["isError"], listing)
        bridge.session.attach(self.openocd(self.rpc))
        self.assertFalse(bridge.call("read_register", {"names": ["PORT.MODE.STATE"]})["isError"])
        self.assertTrue(bridge.call("read_register", {"names": ["PORT.HAZARD"]})["isError"])
        self.assertFalse(mcp_server.TOOLS["read_register"]["mutating"])


@unittest.skipUnless(os.environ.get("EAT_SVD_SMOKE"), "optional: EAT_SVD_SMOKE belirtilmedi")
class SmokeTests(unittest.TestCase):
    def test_all_local_files(self):
        paths = list(Path(os.environ["EAT_SVD_SMOKE"]).rglob("*.svd"))
        self.assertTrue(paths, "SVD dosyası bulunamadı")
        for path in paths:
            with self.subTest(path=path):
                device = svd.Device.load(path)
                for peripheral in device.peripherals():
                    for register in device.registers(peripheral):
                        self.assertIs(device.lookup(register.name), register)
