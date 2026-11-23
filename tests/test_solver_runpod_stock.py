"""Provider availability must match the requested host and volume, without rental."""
import asyncio
import json

import httpx
import pytest

from backend.core.runpod_api import RunpodError
from backend.core.solver_runpod_stock import fetch_solver_stock


@pytest.mark.parametrize('failure', ['', 'volume', 'provider'])
def test_stock_is_scoped_to_volume_and_host(failure):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'networkVolumes': [
                {'id': 'volume', 'dataCenter': 'EU-RO-1', 'size': 200}
            ] if failure != 'volume' else []})
        payload = json.loads(request.content)
        assert 'mutation' not in payload['query']
        constraints = payload['variables']['input']
        assert constraints['dataCenterId'] == 'EU-RO-1'
        assert constraints['minMemoryInGb'] == 81  # 75 GiB in provider decimal GB
        assert constraints['minVcpuCount'] == 8
        assert constraints['gpuCount'] == 1
        assert constraints['secureCloud'] is True
        assert constraints['supportPublicIp'] is True
        assert constraints['minCudaVersion']
        assert constraints['minDisk'] > 0
        if failure == 'provider':
            return httpx.Response(200, json={'errors': [{'message': 'unavailable'}]})
        return httpx.Response(200, json={'data': {'gpuTypes': [
            {'id': 'A100', 'memoryInGb': 80, 'lowestPrice': None},
            {'id': '4090', 'memoryInGb': 24, 'lowestPrice': {'stockStatus': 'Low', 'uninterruptablePrice': .89}},
            {'id': 'AMD GPU', 'memoryInGb': 192},
        ]}})
    async def run():
        return await fetch_solver_stock('test-key', 'volume', 75, 8, transport=httpx.MockTransport(handle))
    if failure:
        with pytest.raises(RunpodError):
            asyncio.run(run())
        assert len(calls) == (1 if failure == 'volume' else 2)
    else:
        stock = asyncio.run(run())
        assert stock['A100']['stock'] == 'None'
        assert stock['4090']['on_demand'] == .89
        assert stock['4090']['data_center_id'] == 'EU-RO-1'
        assert 'AMD GPU' not in stock
