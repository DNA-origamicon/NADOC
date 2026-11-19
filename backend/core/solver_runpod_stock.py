"""Read-only availability matching the solver's volume and host allocation."""
import math
from backend.core.runpod_api import RunpodClient, RunpodError, DEFAULT_ALLOWED_CUDA, DEFAULT_CONTAINER_DISK_GB


async def fetch_solver_stock(api_key, volume_id, mem_gb, cores, *, transport=None):
    client = RunpodClient(api_key, transport=transport)
    try:
        volume = next((v for v in await client.list_network_volumes() if v['id'] == volume_id), None)
        if not volume or not volume.get('data_center_id'):
            raise RunpodError('Select a network volume with a known datacenter before choosing solver resources')
        constraints = dict(dataCenterId=volume['data_center_id'], gpuCount=1, secureCloud=True,
                           minMemoryInGb=math.ceil(mem_gb * 1024**3 / 1e9), minVcpuCount=cores,
                           supportPublicIp=True, minCudaVersion=DEFAULT_ALLOWED_CUDA[0],
                           minDisk=DEFAULT_CONTAINER_DISK_GB)
        query = '''query SolverStock($input: GpuLowestPriceInput!) {
          gpuTypes { id displayName memoryInGb
            lowestPrice(input: $input) { stockStatus uninterruptablePrice }
          }
        }'''
        response = await client._client.post(client._graphql_url, json={'query': query, 'variables': {'input': constraints}})
        if response.status_code != 200 or response.json().get('errors'):
            raise RunpodError('Could not verify RunPod availability for this volume and resource allocation; refresh and try again')
        rows = (response.json().get('data') or {}).get('gpuTypes')
        if rows is None:
            raise RunpodError('RunPod returned no availability data')
        return {row['id']: dict(display=row.get('displayName') or row['id'],
                    vram_gb=row.get('memoryInGb'), stock=(row.get('lowestPrice') or {}).get('stockStatus') or 'None',
                    on_demand=(row.get('lowestPrice') or {}).get('uninterruptablePrice'),
                    data_center_id=volume['data_center_id']) for row in rows if 'AMD' not in row['id'].upper()}
    finally:
        await client.aclose()
