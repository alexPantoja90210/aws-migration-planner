"""Excel -> servers.json, with every interpretation stated rather than assumed."""
import json, collections, openpyxl

SRC = '/root/.claude/uploads/1439f09b-3a7b-5677-918e-b2830817f991/0a12be49-Detalle_Inventario_Servidores.xlsx'

# The planner's contract knows five roles. The inventory uses ten. The mapping is
# cosmetic -- role drives neither the graph nor the sizing -- but it is recorded
# so nobody has to guess later what "app" meant.
ROLE_MAP = {'Web/App':'web', 'Postgres':'db', 'Oracle':'db', 'SQLite':'db',
            'FileServer':'file', 'Utility':'app', 'Batch':'app',
            'Monitoring':'app', 'Logging':'app', 'Tools':'app'}

rows = [r for r in openpyxl.load_workbook(SRC, data_only=True)['Hoja1']
        .iter_rows(min_row=2, values_only=True) if r[0] is not None]
names = {str(r[1]).strip() for r in rows}

servers, kept, dropped = [], 0, collections.Counter()
for r in rows:
    sid, name, role, os_, cpu, ram, disk, dep, ports, dbsz, folders = [
        (str(x).strip() if x is not None else '') for x in r]
    # ONLY a dependency value that resolves to a server in this inventory is an
    # edge. Everything else in that column is a different relation written in
    # the same place -- consumed-by, watched-by, used-by-department -- and is
    # dropped rather than guessed at.
    if dep in names:
        deps = [dep]; kept += 1
    else:
        deps = []
        if dep.lower() not in ('ninguna', 'none', ''):
            dropped[dep] = dropped[dep] + 1
    servers.append({
        'id': name, 'os': os_.lower(), 'cpu': int(cpu), 'ram': int(ram),
        'storage': int(disk), 'role': ROLE_MAP[role], 'dependencies': deps,
        'source_role': role, 'source_id': int(sid),
    })

json.dump(servers, open('servers.json','w'), indent=2, ensure_ascii=False)
print('%d servidores | %d aristas conservadas | %d valores descartados (%d distintos)'
      % (len(servers), kept, sum(dropped.values()), len(dropped)))

# The four waves as the humans drew them, by the ID ranges in the first workbook.
by_src = {s['source_id']: s['id'] for s in servers}
excel_waves = [[by_src[i] for i in rng] for rng in
               (range(1,21), range(21,61), range(61,81), range(81,101))]
json.dump(excel_waves, open('excel_waves.json','w'), indent=2)
print('olas del Excel:', [len(w) for w in excel_waves])
