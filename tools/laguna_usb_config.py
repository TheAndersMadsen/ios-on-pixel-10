#!/usr/bin/env python3
"""Validate the laguna live FDT USB topology and emit shim constants.

Static topology only: no MMIO/device access and no claim that clocks, resets,
Type-C state, reserved-pool ownership, SMMU translation or DMA is operational.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("laguna_dtb_inventory", ROOT / "research/workspace/hardware/analyze_dtb.py")
_dtb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dtb)

USB_BUS = "/simple_usb_bus"
WRAPPER = USB_BUS + "/usb3@c450000"
DWC3 = WRAPPER + "/dwc3@c400000"
PHY = "/usb_phy@c410000"
REPEATER = "/i2c@3a331000/tiusb2e11@3E"
DMA_NODE = "/reserved-memory/xhci_dma_buffer@9050000"


def _enabled(node):
    current = node
    while current:
        status = current.names("status")
        if status and status[0] not in ("ok", "okay"):
            return False
        current = current.parent
    return True


def _one(nodes, path, compatible=None):
    if path not in nodes:
        raise ValueError(f"missing {path}")
    node = nodes[path]
    if not _enabled(node):
        raise ValueError(f"disabled {path}")
    if compatible and compatible not in node.names("compatible"):
        raise ValueError(f"{path}: expected compatible {compatible}")
    return node


def _regs(node):
    result = []
    for reg in _dtb.registers(node):
        if reg.get("cpu_address") is None or reg.get("size") is None:
            raise ValueError(f"{node.path}: untranslated MMIO range")
        result.append((reg.get("name"), int(reg["cpu_address"], 16), int(reg["size"], 16)))
    return result


def _expect_regs(node, expected):
    actual = _regs(node)
    wanted = [(name, address, size) for name, address, size in expected]
    if actual != wanted:
        raise ValueError(f"{node.path}: register layout changed: {actual!r}")


def _cell(node, prop):
    value = node.uint(prop)
    if value is None:
        raise ValueError(f"{node.path}: missing {prop}")
    return value


def _clock(node, index, expected_path, expected_id):
    deps = _dtb.dependencies(node, _phandles(_all_nodes))
    item = deps.get("clocks", [])[index]
    if item.get("path") != expected_path or item.get("error"):
        raise ValueError(f"{node.path}: clock {index} provider changed")
    provider = _all_nodes[expected_path]
    if _cell(provider, "lpcm-id") != 5 or _cell(provider, "clock-id") != expected_id:
        raise ValueError(f"{node.path}: clock {index} firmware ID changed")


def _reset(node, index, expected_id):
    deps = _dtb.dependencies(node, _phandles(_all_nodes))
    item = deps.get("resets", [])[index]
    if item.get("path") != "/cpm_rst/hsion_resets" or item.get("args") != [hex(expected_id)]:
        raise ValueError(f"{node.path}: reset {index} changed")
    provider = _all_nodes[item["path"]]
    if _cell(provider, "lpcm-id") != 5 or _cell(provider, "reset-num") != 0x10:
        raise ValueError("HSION reset provider changed")


def _phandles(nodes):
    result = {}
    for node in nodes.values():
        value = node.uint("phandle", node.uint("linux,phandle"))
        if value is not None:
            result[value] = node
    return result


def configuration(data):
    global _all_nodes
    parsed = _dtb.parse_dtb(data)
    _all_nodes = {node.path: node for node in parsed}
    nodes = _all_nodes
    root = nodes["/"]
    if "google,lga" not in root.names("compatible"):
        raise ValueError("not a laguna FDT")
    if nodes[USB_BUS].props.get("ranges") != b"" or nodes[WRAPPER].props.get("ranges") != b"":
        raise ValueError("USB bus must have identity ranges")

    wrapper = _one(nodes, WRAPPER, "google,dwc3-lga")
    dwc3 = _one(nodes, DWC3, "snps,dwc3")
    phy = _one(nodes, PHY, "google,usb_phy-lga")
    repeater = _one(nodes, REPEATER, "goog-eusb2-repeater")
    dma = _one(nodes, DMA_NODE, "shared-dma-pool")
    _one(nodes, "/cpm_clk", "google,cpm-clk")
    _one(nodes, "/cpm_rst", "google,cpm-rst")
    _one(nodes, "/power_controller", "google,lga-power-controller")
    _one(nodes, "/amb_smmu", "arm,smmu-v3")

    _expect_regs(wrapper, [
        ("usbcs_host_cfg_csr", 0x0c450000, 0x14),
        ("usbcs_usbint_csr", 0x0c450020, 0x08),
        ("usb_top_cfg_csr", 0x0c450028, 0x04),
    ])
    _expect_regs(dwc3, [(None, 0x0c400000, 0xd060)])
    phy_regs = [
        ("dptx_phy_regs", 0x0c410000, 0x10000),
        ("dptx_tca_regs", 0x0c430000, 0x1000),
        ("usb2_cfg_csr", 0x0c450014, 0x0c),
        ("dp_top_csr", 0x0c637000, 0xa0),
        ("gp_ss_csr", 0x0c260000, 0x38),
        ("phy_sram", 0x0c420000, 0x10000),
        ("dp_pipe_lane0", 0x0c480000, 0x3e8),
        ("dp_pipe_lane1", 0x0c490000, 0x3e8),
        ("dwc3_lcsr_deemph", 0x0c40d060, 0x10),
    ]
    _expect_regs(phy, phy_regs)
    _expect_regs(dma, [(None, 0x09050000, 0xc000)])
    if "no-map" not in dma.props:
        raise ValueError("candidate USB DMA pool is not no-map")
    if dwc3.names("role-switch-default-mode") != ["peripheral"]:
        raise ValueError("DWC3 is not peripheral by default")
    if "memory-swap-enabled" not in dwc3.props:
        raise ValueError("review changed DWC3 memory-swap property")

    for i, (path, clock_id) in enumerate([
        ("/cpm_clk/hsion_usbc_non_sticky_clk", 0x07),
        ("/cpm_clk/hsion_usbc_sticky_clk", 0x08),
        ("/cpm_clk/hsion_u2phy_apb_clk", 0x0e),
    ]):
        _clock(wrapper, i, path, clock_id)
    for i, reset_id in enumerate([0x0a, 0x0b, 0x0c, 0x09, 0x06]):
        _reset(wrapper, i, reset_id)
    for i, (path, clock_id) in enumerate([
        ("/cpm_clk/hsion_usb2_phy_reset_clk", 0x11),
        ("/cpm_clk/hsion_usb3dp_phy_reset_clk", 0x12),
        ("/cpm_clk/hsion_phy_fw_clk", 0x03),
    ]):
        _clock(phy, i, path, clock_id)
    for i, reset_id in enumerate([0x0d, 0x0e]):
        _reset(phy, i, reset_id)

    for path, subdomain in [("/power_controller/hsio_n_usb_pd", 0),
                            ("/power_controller/hsio_n_usb_psw_pd", 5)]:
        power = _one(nodes, path)
        if _cell(power, "sswrp-id") != 0x17 or _cell(power, "subdomain-id") != subdomain:
            raise ValueError(f"{path}: firmware power ID changed")
    hsion = _one(nodes, "/power_controller/sswrp_hsio_n_pd")
    if _cell(hsion, "sswrp-id") != 0x17:
        raise ValueError("HSIO_N power provider changed")

    phandles = _phandles(nodes)
    deps = _dtb.dependencies(dwc3, phandles)
    iommus = deps.get("iommus", [])
    if len(iommus) != 1 or iommus[0].get("path") != "/amb_smmu" or iommus[0].get("args") != ["0x8100"]:
        raise ValueError("DWC3 IOMMU stream changed")
    memory_regions = deps.get("memory-region", [])
    if DMA_NODE not in [item.get("path") for item in memory_regions]:
        raise ValueError("candidate DMA pool is not referenced by DWC3")
    if _cell(repeater, "reg") != 0x3e:
        raise ValueError("TUSB2E11 repeater I2C address changed")

    return {
        "format_version": 1,
        "dtb_sha256": hashlib.sha256(data).hexdigest(),
        "hardware_verified": False,
        "dwc3": {"base": "0x0c400000", "size": "0xd060", "role": "peripheral"},
        "usb2_cfg_base": "0x0c450014",
        "usbdp_top_base": "0x0c637000",
        "phy_regions": [{"name": n, "base": hex(a), "size": hex(s)} for n, a, s in phy_regs],
        "usb2_warm_resume": {
            "power_hierarchy": ["sswrp_hsio_n_pd", "hsio_n_usb_pd/subdomain0", "hsio_n_usb_psw_pd/subdomain5"],
            "lpcm_id": 5,
            "clock_ids": [0x07, 0x08, 0x0e, 0x11],
            "reset_ids": [0x0a, 0x0b, 0x0c, 0x09, 0x06, 0x0d],
            "repeater": REPEATER,
            "preserve": ["USB2PHY_CFG19 PLL feedback", "NVMEM tuning", "Type-C orientation", "USB3/DP firmware"],
        },
        "dma_candidate": {
            "path": DMA_NODE, "base": "0x09050000", "size": "0xc000", "no_map": True,
            "admitted": False,
            "reason": "DT reservation does not prove current ownership, CPU accessibility, SMMU translation or quiescence",
        },
        "review_required": ["amb_smmu stream 0x8100", "memory-swap-enabled semantics", "CPM transport", "Type-C/repeater handoff"],
    }


def emit_header(result):
    dma = result["dma_candidate"]
    return f"""/* Generated from live FDT {result['dtb_sha256']}; static topology only. */
#pragma once
#define LAGUNA_USB_DWC3_BASE 0x0c400000ULL
#define LAGUNA_USB2_CFG_BASE 0x0c450014ULL
#define LAGUNA_USBDPTOP_BASE 0x0c637000ULL
/* Candidate only: NOT an admission or ownership proof. */
#define LAGUNA_USB_CANDIDATE_DMA_PA {dma['base']}ULL
#define LAGUNA_USB_CANDIDATE_DMA_SIZE {dma['size']}ULL
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--header", type=Path)
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    result = configuration(args.dtb.read_bytes())
    if args.header:
        args.header.parent.mkdir(parents=True, exist_ok=True)
        args.header.write_text(emit_header(result))
    text = json.dumps(result, indent=2) + "\n"
    if args.inventory:
        args.inventory.parent.mkdir(parents=True, exist_ok=True)
        args.inventory.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, IndexError, KeyError) as exc:
        raise SystemExit(f"laguna_usb_config: {exc}") from exc
