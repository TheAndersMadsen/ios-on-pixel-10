import unittest
from pathlib import Path

from laguna_usb_config import configuration, emit_header

DTB = Path(__file__).resolve().parents[1] / "research/workspace/hardware/bootchain-20261022/live-fdt.dtb"


class LagunaUSBConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DTB.read_bytes()
        cls.result = configuration(cls.data)

    def test_live_fdt_exact_topology(self):
        r = self.result
        self.assertEqual(r["dtb_sha256"], "d7c27fdc8657be6e6a378aa0a622dee6508ef24e88c313084ff9de61222bd306")
        self.assertEqual(r["dwc3"], {"base": "0x0c400000", "size": "0xd060", "role": "peripheral"})
        self.assertEqual(r["usb2_warm_resume"]["clock_ids"], [7, 8, 14, 17])
        self.assertEqual(r["usb2_warm_resume"]["reset_ids"], [10, 11, 12, 9, 6, 13])
        self.assertEqual(len(r["phy_regions"]), 9)
        self.assertEqual(r["phy_regions"][2], {"name": "usb2_cfg_csr", "base": "0xc450014", "size": "0xc"})
        self.assertFalse(r["hardware_verified"])

    def test_dma_candidate_is_not_admission(self):
        dma = self.result["dma_candidate"]
        self.assertEqual((dma["base"], dma["size"]), ("0x09050000", "0xc000"))
        self.assertTrue(dma["no_map"])
        self.assertFalse(dma["admitted"])
        self.assertIn("amb_smmu stream 0x8100", self.result["review_required"])
        header = emit_header(self.result)
        self.assertIn("LAGUNA_USB_CANDIDATE_DMA_PA 0x09050000ULL", header)
        self.assertNotIn("ADMITTED", header.upper().replace("ADMISSION", ""))

    def test_fail_closed_mutations(self):
        cases = []
        cases.append(self.data.replace(b"google,lga\0", b"google,lgx\0", 1))
        dwc3_reg = bytes.fromhex("000000000c400000000000000000d060")
        self.assertEqual(self.data.count(dwc3_reg), 1)
        cases.append(self.data.replace(dwc3_reg, bytes.fromhex("000000000c400100000000000000d060"), 1))
        cases.append(self.data.replace(b"peripheral\0", b"host\0xxxxxx", 1))
        cases.append(self.data.replace(b"memory-swap-enabled\0", b"memory-swap-disable\0", 1))
        for changed in cases:
            with self.subTest(changed=len(changed)):
                with self.assertRaises((ValueError, KeyError, IndexError)):
                    configuration(changed)


if __name__ == "__main__":
    unittest.main()
