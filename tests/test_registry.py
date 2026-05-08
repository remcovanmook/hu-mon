"""
tests.test_registry
~~~~~~~~~~~~~~~~~~~~
Unit tests for growatt.drivers.registry.

Tests the four-stage probe pipeline using mocked Modbus clients, and validates
auto_select() behaviour including the --driver force override.
"""

import unittest
from unittest.mock import MagicMock, call

from growatt.drivers.base import BaseDriver, DeviceInfo, ProbeContext, ProxyConfig
from growatt.drivers.registry import (
    DRIVER_REGISTRY,
    _BLOCK_CHUNK_SIZES,
    _SLAVE_ID_CANDIDATES,
    _detect_function_codes,
    _discover_slave_id,
    _read_holding_block,
    auto_select,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(values=None):
    r = MagicMock()
    r.isError.return_value = False
    r.registers = values or [0]
    return r


def _err():
    r = MagicMock()
    r.isError.return_value = True
    return r


def _mock_driver(driver_id="mock", probe_result=True):
    """Return a minimal BaseDriver implementation."""
    class _MockDriver(BaseDriver):
        @property
        def driver_id(self): return driver_id
        def probe(self, ctx): return probe_result
        def read_device_info(self, c, s): raise NotImplementedError
        def read_registers(self, c, s): raise NotImplementedError
        @property
        def proxy_config(self): return ProxyConfig(address_map={1: {3: [], 4: []}})
    return _MockDriver


# ---------------------------------------------------------------------------
# Stage 1: Slave ID discovery
# ---------------------------------------------------------------------------

class TestDiscoverSlaveId(unittest.TestCase):

    def test_first_candidate_responds(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _ok()
        slave_id = _discover_slave_id(client)
        self.assertEqual(slave_id, _SLAVE_ID_CANDIDATES[0])

    def test_second_candidate_wins_when_first_fails(self):
        client = MagicMock()
        client.read_holding_registers.side_effect = [_err(), _ok()]
        slave_id = _discover_slave_id(client)
        self.assertEqual(slave_id, _SLAVE_ID_CANDIDATES[1])

    def test_last_candidate_wins(self):
        client = MagicMock()
        side_effects = [_err()] * (len(_SLAVE_ID_CANDIDATES) - 1) + [_ok()]
        client.read_holding_registers.side_effect = side_effects
        slave_id = _discover_slave_id(client)
        self.assertEqual(slave_id, _SLAVE_ID_CANDIDATES[-1])

    def test_no_response_returns_none(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _err()
        slave_id = _discover_slave_id(client)
        self.assertIsNone(slave_id)

    def test_exception_during_probe_does_not_raise(self):
        client = MagicMock()
        client.read_holding_registers.side_effect = ConnectionError("refused")
        slave_id = _discover_slave_id(client)
        self.assertIsNone(slave_id)


# ---------------------------------------------------------------------------
# Stage 2: Function code detection
# ---------------------------------------------------------------------------

class TestDetectFunctionCodes(unittest.TestCase):

    def test_both_fcs_supported(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _ok()
        client.read_input_registers.return_value = _ok()
        fcs = _detect_function_codes(client, slave_id=1)
        self.assertEqual(fcs, {3, 4})

    def test_only_holding_supported(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _ok()
        client.read_input_registers.return_value = _err()
        fcs = _detect_function_codes(client, slave_id=1)
        self.assertEqual(fcs, {3})

    def test_neither_supported(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _err()
        client.read_input_registers.return_value = _err()
        fcs = _detect_function_codes(client, slave_id=1)
        self.assertEqual(fcs, set())


# ---------------------------------------------------------------------------
# Stage 3: Holding block read
# ---------------------------------------------------------------------------

class TestReadHoldingBlock(unittest.TestCase):

    def _client_with_chunk_size(self, accepted_size: int):
        """Client that accepts exactly accepted_size registers per request."""
        client = MagicMock()
        def side_effect(addr, count, device_id):
            if count <= accepted_size:
                return _ok([0] * count)
            return _err()
        client.read_holding_registers.side_effect = side_effect
        return client

    def test_full_block_in_one_request(self):
        client = self._client_with_chunk_size(125)
        block, max_size = _read_holding_block(client, slave_id=1)
        self.assertIsNotNone(block)
        self.assertEqual(len(block), 125)
        self.assertEqual(max_size, 125)

    def test_falls_back_to_64(self):
        client = self._client_with_chunk_size(64)
        block, max_size = _read_holding_block(client, slave_id=1)
        self.assertIsNotNone(block)
        self.assertEqual(max_size, 64)

    def test_falls_back_to_32(self):
        client = self._client_with_chunk_size(32)
        block, max_size = _read_holding_block(client, slave_id=1)
        self.assertIsNotNone(block)
        self.assertEqual(max_size, 32)

    def test_falls_back_to_16(self):
        client = self._client_with_chunk_size(16)
        block, max_size = _read_holding_block(client, slave_id=1)
        self.assertIsNotNone(block)
        self.assertEqual(max_size, 16)

    def test_all_sizes_fail_returns_none(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _err()
        block, max_size = _read_holding_block(client, slave_id=1)
        self.assertIsNone(block)
        self.assertEqual(max_size, 0)


# ---------------------------------------------------------------------------
# Stage 4 / auto_select
# ---------------------------------------------------------------------------

class TestAutoSelect(unittest.TestCase):

    def _client_ok(self):
        """Client that always responds successfully."""
        client = MagicMock()
        client.read_holding_registers.return_value = _ok([0] * 125)
        client.read_input_registers.return_value = _ok([0])
        return client

    def test_returns_matching_driver(self):
        client = self._client_ok()
        MockDriver = _mock_driver(driver_id="mock", probe_result=True)
        original = list(DRIVER_REGISTRY)
        DRIVER_REGISTRY.clear()
        DRIVER_REGISTRY.append(MockDriver)
        try:
            driver, slave_id = auto_select(client)
            self.assertEqual(driver.driver_id, "mock")
            self.assertIn(slave_id, _SLAVE_ID_CANDIDATES)
        finally:
            DRIVER_REGISTRY.clear()
            DRIVER_REGISTRY.extend(original)

    def test_raises_when_no_driver_matches(self):
        client = self._client_ok()
        MockDriver = _mock_driver(driver_id="mock", probe_result=False)
        original = list(DRIVER_REGISTRY)
        DRIVER_REGISTRY.clear()
        DRIVER_REGISTRY.append(MockDriver)
        try:
            with self.assertRaises(RuntimeError):
                auto_select(client)
        finally:
            DRIVER_REGISTRY.clear()
            DRIVER_REGISTRY.extend(original)

    def test_raises_when_no_slave_responds(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _err()
        client.read_input_registers.return_value = _err()
        with self.assertRaises(RuntimeError):
            auto_select(client)

    def test_force_driver_id_selects_by_id(self):
        client = self._client_ok()
        MockDriver = _mock_driver(driver_id="my_driver", probe_result=False)
        original = list(DRIVER_REGISTRY)
        DRIVER_REGISTRY.clear()
        DRIVER_REGISTRY.append(MockDriver)
        try:
            driver, _ = auto_select(client, force_driver_id="my_driver")
            self.assertEqual(driver.driver_id, "my_driver")
        finally:
            DRIVER_REGISTRY.clear()
            DRIVER_REGISTRY.extend(original)

    def test_force_driver_id_unknown_raises_value_error(self):
        client = self._client_ok()
        with self.assertRaises(ValueError):
            auto_select(client, force_driver_id="does_not_exist")


if __name__ == '__main__':
    unittest.main()
