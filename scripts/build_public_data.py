"""Versioned first screen, complete catalog, and on-demand source details."""
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG_FIELDS = ('id','title','authors','journal','published','first_seen','doi','url','topics','methods',
                  'tracts','is_preprint','is_review','is_monitored_journal','summary_zh','evidence','relevance')
META_FIELDS = ('schema_version','updated_at','as_of','initial_coverage_start','update_mode','update_summary',
               'topics','monitored_journals','relevance_status')


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n').encode()


def bucket(paper_id):
    return hashlib.sha256(paper_id.encode()).hexdigest()[:2]


def build(data, folder):
    raw = encoded(data)
    version = hashlib.sha256(raw).hexdigest()[:20]
    asset = folder/'assets-data'/version
    asset.mkdir(parents=True,exist_ok=True)
    (folder/'data.json.gz').write_bytes(gzip.compress((folder/'data.json').read_bytes(),mtime=0))
    (asset/'full.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    (asset/'full.json').write_bytes(raw)
    catalog = {k:data[k] for k in META_FIELDS if k in data}
    catalog['version'] = version
    catalog['papers'] = []
    details, search = {}, {}
    for p in data['papers']:
        item = {k:p[k] for k in CATALOG_FIELDS if k in p}
        item['detail_bucket'] = bucket(p['id'])
        item['has_abstract'] = bool(p.get('abstract','').strip())
        if not p.get('summary_zh'):
            item['abstract_preview'] = p.get('abstract','')[:280]
        catalog['papers'].append(item)
        details.setdefault(item['detail_bucket'],{})[p['id']] = {k:p.get(k) for k in
            ('abstract','indexed','source','source_id','source_url','summary_meta')}
        search[p['id']] = p.get('abstract','')
    for name,value in [('catalog',catalog),('search',search)]:
        content = encoded(value)
        (asset/(name+'.json')).write_bytes(content)
        (asset/(name+'.json.gz')).write_bytes(gzip.compress(content,mtime=0))
    for key,value in details.items():
        (asset/(key+'.json')).write_bytes(encoded(value))
    prefix = './assets-data/'+version+'/'
    manifest = {'schema_version':1,'version':version,'catalog':prefix+'catalog.json','search':prefix+'search.json',
                'full':prefix+'full.json','details':prefix,'updated_at':data['updated_at']}
    (folder/'manifest.json').write_bytes(encoded(manifest))
    initial = {**catalog,'papers':sorted(catalog['papers'],key=lambda p:(-int(p['published'].replace('-','')),p['title']))[:50],
               'partial':True,'total':len(data['papers']),'topic_counts':{t['id']:sum(t['id'] in p['topics'] for p in data['papers']) for t in data['topics']},
               'manifest':manifest}
    html_path = folder/'index.html'
    html = html_path.read_text(encoding='utf-8')
    block = '<!-- initial-data:start --><script type="application/json" id="initial-data">'+encoded(initial).decode().replace('<','\\u003c')+'</script><!-- initial-data:end -->'
    if '<!-- initial-data:start -->' in html:
        html = re.sub(r'<!-- initial-data:start -->.*?<!-- initial-data:end -->',lambda _:block,html,flags=re.S)
    else:
        html = html.replace('</head>',block+'\n</head>')
    html_path.write_text(html,encoding='utf-8')
    print(f'Built {version}: first screen {len(gzip.compress(encoded(initial))):,} bytes; catalog {len(gzip.compress(encoded(catalog))):,} bytes gzip; details on demand.')
    return manifest


if __name__ == '__main__':
    folder = ROOT/'dist'
    build(json.loads((folder/'data.json').read_text(encoding='utf-8')),folder)
