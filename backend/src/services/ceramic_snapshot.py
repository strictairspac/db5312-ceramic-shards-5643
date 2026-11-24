from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Node:
    weight: int | float
    capacity: int
    other_used: int


@dataclass(frozen=True)
class Batch:
    identity: str
    current_owner: str
    size: int


@dataclass(frozen=True)
class Snapshot:
    identity: str
    budget: int
    nodes: dict[str, Node]
    batches: list[Batch]
    initial_used: dict[str, int]


def _identifier(value, label):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f'{label}须为非空文本，且首尾不能有空白')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{label}须为有效 UTF-8 文本') from exc
    return value


def _byte_count(value, minimum, label):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label}须为不小于 {minimum} 的整数字节数')
    return value


def _rows(payload, key, label):
    rows = payload.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'{label}须为对象列表')
    return rows


def read_snapshot(payload):
    if not isinstance(payload, dict):
        raise ValueError('分片盘点须为对象')
    identity = _identifier(payload.get('snapshot_id'), '盘点编号')
    budget = _byte_count(payload.get('round_budget_bytes'), 0, '轮次预算')

    nodes = {}
    for index, row in enumerate(_rows(payload, 'nodes', '窑口节点'), start=1):
        node_id = _identifier(row.get('node_id'), f'第 {index} 行节点编号')
        if node_id in nodes:
            raise ValueError(f'节点编号重复：{node_id}')
        weight = row.get('weight')
        if (type(weight) not in (int, float) or weight < 0
                or (type(weight) is float and not isfinite(weight))):
            raise ValueError(f'节点 {node_id} 的目标权重须为有限非负数')
        capacity = _byte_count(row.get('capacity_bytes'), 0, f'节点 {node_id} 的物理容量')
        other_used = _byte_count(row.get('other_used_bytes'), 0, f'节点 {node_id} 的其他占用')
        nodes[node_id] = Node(weight, capacity, other_used)
    if not any(node.weight > 0 for node in nodes.values()):
        raise ValueError('至少需要一个目标权重大于零的节点')

    initial_used = {node_id: node.other_used for node_id, node in nodes.items()}
    batches = []
    seen = set()
    for index, row in enumerate(_rows(payload, 'batches', '预检批次'), start=1):
        batch_id = _identifier(row.get('batch_id'), f'第 {index} 行批次编号')
        if batch_id in seen:
            raise ValueError(f'批次编号重复：{batch_id}')
        seen.add(batch_id)
        owner = _identifier(row.get('current_owner'), f'批次 {batch_id} 的现有归属')
        if owner not in nodes:
            raise ValueError(f'批次 {batch_id} 的现有归属 {owner} 未在节点盘点中')
        size = _byte_count(row.get('size_bytes'), 1, f'批次 {batch_id} 的占用')
        batches.append(Batch(batch_id, owner, size))
        initial_used[owner] += size

    for node_id, used in initial_used.items():
        capacity = nodes[node_id].capacity
        if used > capacity:
            raise ValueError(f'节点 {node_id} 的盘点占用 {used} 字节超过物理容量 {capacity} 字节')
    batches.sort(key=lambda batch: batch.identity)
    return Snapshot(identity, budget, dict(sorted(nodes.items())), batches, initial_used)
