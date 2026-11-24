import hashlib
import json
import math

from src.services.ceramic_snapshot import read_snapshot


SPEC = {
    'name': '陶驿窑务·预检记录分片',
    'summary': '比较陶坯预检批次的现有归属和目标归属，按节点余量与轮次预算生成搬迁清单。',
    'customer': '陶驿陶业·窑务数据值班组',
    'entity_labels': ['预检批次盘点', '重分片试算', '搬迁清单'],
    'field_labels': {
        'snapshot_id': '盘点编号',
        'round_budget_bytes': '本轮搬迁预算（字节）',
        'nodes': '窑口节点',
        'node_id': '节点编号',
        'weight': '目标权重（零为排空）',
        'capacity_bytes': '物理容量（字节）',
        'other_used_bytes': '批次之外的占用（字节）',
        'batches': '预检批次',
        'batch_id': '批次编号',
        'current_owner': '现有归属',
        'size_bytes': '批次占用（字节）',
    },
    'guidance': '录入同一时点的节点占用和批次归属。排空节点保留在盘点中，权重设为零。按清单序号执行并逐批确认。',
    'sample': {
        'snapshot_id': 'TY-20261121-0800',
        'round_budget_bytes': 150_000_000,
        'nodes': [
            {'node_id': 'EAST', 'weight': 1, 'capacity_bytes': 240_000_000, 'other_used_bytes': 60_000_000},
            {'node_id': 'NORTH', 'weight': 3, 'capacity_bytes': 160_000_000, 'other_used_bytes': 65_000_000},
            {'node_id': 'WEST', 'weight': 2, 'capacity_bytes': 176_000_000, 'other_used_bytes': 45_000_000},
            {'node_id': 'OLD', 'weight': 0, 'capacity_bytes': 170_000_000, 'other_used_bytes': 20_000_000},
        ],
        'batches': [
            {'batch_id': 'TY-1121-01', 'current_owner': 'EAST', 'size_bytes': 32_000_000},
            {'batch_id': 'TY-1121-02', 'current_owner': 'OLD', 'size_bytes': 70_000_000},
            {'batch_id': 'TY-1121-03', 'current_owner': 'OLD', 'size_bytes': 50_000_000},
            {'batch_id': 'TY-1121-04', 'current_owner': 'EAST', 'size_bytes': 55_000_000},
            {'batch_id': 'TY-1121-05', 'current_owner': 'EAST', 'size_bytes': 30_000_000},
        ],
    },
    'expect': {'归属变化批次': 4, '计划搬迁批次': 2, '计划搬迁字节': 120_000_000, '待排批次': 2},
}


def validate(payload):
    read_snapshot(payload)


def _score(batch_id, node_id, log_weight):
    key = json.dumps([batch_id, node_id], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    prefix = int.from_bytes(hashlib.sha256(key).digest()[:7], 'big') >> 4
    # Midpoints in (0, 1) keep the logarithms finite even at either hash endpoint.
    uniform = (prefix + 0.5) / (1 << 52)
    return math.log(-math.log(uniform)) - log_weight


def _schedule(snapshot, changed, proposed):
    used = snapshot.initial_used.copy()
    remaining = snapshot.budget
    manifest = []
    pending = sorted(
        changed, key=lambda batch: (snapshot.nodes[batch.current_owner].weight > 0, batch.identity)
    )
    while pending:
        moves_before = len(manifest)
        waiting_for_space = []
        for batch in pending:
            source = batch.current_owner
            target = proposed[batch.identity]
            if batch.size > remaining:
                continue
            available = snapshot.nodes[target].capacity - used[target]
            if batch.size > available:
                waiting_for_space.append(batch)
                continue

            # Reserve the incoming copy before releasing its source in the simulation.
            used[target] += batch.size
            used[source] -= batch.size
            remaining -= batch.size
            manifest.append({
                '序号': len(manifest) + 1,
                '盘点编号': snapshot.identity,
                '批次编号': batch.identity,
                '源节点': source,
                '目标节点': target,
                '搬迁字节': batch.size,
                '复制前目标可用字节': available,
                '完成后目标可用字节': available - batch.size,
                '完成后预算余量字节': remaining,
            })
        if len(manifest) == moves_before:
            break
        pending = waiting_for_space
    return manifest, used, remaining


def _deferral(size, free, remaining, initial_budget):
    reasons = []
    if size > free:
        reasons.append('目标容量不足')
    if size > initial_budget:
        reasons.append('单批超过整轮预算')
    elif size > remaining:
        reasons.append('本轮剩余预算不足')
    return '、'.join(reasons)


def solve(payload, engine):
    snapshot = read_snapshot(payload)
    log_weights = {
        node_id: math.log(node.weight) for node_id, node in snapshot.nodes.items() if node.weight > 0
    }
    proposed = {
        batch.identity: min(
            log_weights, key=lambda node_id: (_score(batch.identity, node_id, log_weights[node_id]), node_id)
        )
        for batch in snapshot.batches
    }
    changed = [batch for batch in snapshot.batches if proposed[batch.identity] != batch.current_owner]
    manifest, used, remaining = _schedule(snapshot, changed, proposed)
    planned = {row['批次编号'] for row in manifest}

    desired_used = {node_id: node.other_used for node_id, node in snapshot.nodes.items()}
    comparisons = []
    for batch in snapshot.batches:
        target = proposed[batch.identity]
        desired_used[target] += batch.size
        if target == batch.current_owner:
            status, reason = '保留', '归属一致'
        elif batch.identity in planned:
            status, reason = '本轮搬迁', '已列入清单'
        else:
            status = '待排'
            reason = _deferral(batch.size, snapshot.nodes[target].capacity - used[target], remaining, snapshot.budget)
        comparisons.append({
            '批次编号': batch.identity,
            '批次字节': batch.size,
            '现有归属': batch.current_owner,
            '计算归属': target,
            '本轮结束归属': target if batch.identity in planned else batch.current_owner,
            '判定': status,
            '原因': reason,
        })

    node_rows = [
        {
            '节点编号': node_id,
            '目标权重': node.weight,
            '物理容量字节': node.capacity,
            '其他占用字节': node.other_used,
            '盘点占用字节': snapshot.initial_used[node_id],
            '完全按计算归属时占用字节': desired_used[node_id],
            '本轮结束占用字节': used[node_id],
            '本轮结束可用字节': node.capacity - used[node_id],
        }
        for node_id, node in snapshot.nodes.items()
    ]
    deferred_count = len(changed) - len(manifest)
    moved_bytes = snapshot.budget - remaining
    return {
        'summary': f'盘点 {snapshot.identity} 有 {len(changed)} 批归属变化，本轮可搬 {len(manifest)} 批共 '
                   f'{moved_bytes} 字节，待排 {deferred_count} 批。',
        'metrics': {
            '批次总数': len(snapshot.batches),
            '归属变化批次': len(changed),
            '归属变化字节': sum(batch.size for batch in changed),
            '计划搬迁批次': len(manifest),
            '计划搬迁字节': moved_bytes,
            '待排批次': deferred_count,
            '轮次预算字节': snapshot.budget,
            '剩余预算字节': remaining,
        },
        'sections': [
            {'title': '本轮搬迁清单', 'rows': manifest},
            {'title': '批次归属比较', 'rows': comparisons},
            {'title': '节点物理占用', 'rows': node_rows},
        ],
    }
