"""Read newly indexed journal articles directly from NCBI E-utilities."""
import datetime as dt
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'


def request(endpoint, **params):
    time.sleep(1)
    body = urlencode({'db': 'pubmed', 'tool': 'NeuroBrief', **params}).encode()
    req = Request(API + endpoint + '.fcgi', data=body, headers={'User-Agent': 'NeuroBrief literature updates'})
    with urlopen(req, timeout=45) as response:
        return response.read()


def exact_date(node):
    if node is None:
        return None
    try:
        month = node.findtext('Month', '')
        if not month.isdecimal():
            month = dt.datetime.strptime(month[:3], '%b').month
        return dt.date(int(node.findtext('Year', '')), int(month), int(node.findtext('Day', ''))).isoformat()
    except ValueError:
        return None


def text(node):
    return ''.join(node.itertext()).strip() if node is not None else ''


def article_row(record):
    citation = record.find('MedlineCitation')
    article = record.find('MedlineCitation/Article')
    pmid = record.findtext('MedlineCitation/PMID')
    if article is None or not pmid:
        return None
    journal = article.find('Journal')
    history = record.findall('PubmedData/History/PubMedPubDate')
    dates = article.findall('ArticleDate') + article.findall('Journal/JournalIssue/PubDate')
    dates += [date for date in history if date.get('PubStatus') in ('epublish', 'ppublish', 'aheadofprint')]
    published = min((value for date in dates if (value := exact_date(date))), default=None)
    indexed = next((exact_date(date) for date in history if date.get('PubStatus') == 'pubmed'), None)
    doi = record.findtext("PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
    if not doi:
        doi = article.findtext("ELocationID[@EIdType='doi']")
    authors = []
    for author in article.findall('AuthorList/Author'):
        authors.append(author.findtext('CollectiveName') or ' '.join(
            part for part in (author.findtext('LastName'), author.findtext('Initials')) if part))
    abstract = []
    for part in article.findall('Abstract/AbstractText'):
        label = part.get('Label')
        if text(part):
            abstract.append((label + ': ' if label else '') + text(part))
    issn = journal.findtext('ISSN') if journal is not None else None
    return {
        'source': 'MED', 'id': pmid, 'doi': doi,
        'title': text(article.find('ArticleTitle')), 'authorString': ', '.join(filter(None, authors)),
        'abstractText': ' '.join(abstract), 'firstPublicationDate': published, 'firstIndexDate': indexed,
        'pubYear': (published or '')[:4],
        'journalInfo': {'journal': {'title': article.findtext('Journal/Title'), 'issn': issn,
                                    'essn': citation.findtext('MedlineJournalInfo/ISSNLinking')}},
        'pubTypeList': {'pubType': [text(p) for p in article.findall('PublicationTypeList/PublicationType')]},
        'keywordList': {'keyword': [text(k) for k in citation.findall('KeywordList/Keyword')]},
        'meshHeadingList': {'meshHeading': [{'descriptorName': text(k)} for k in citation.findall('MeshHeadingList/MeshHeading/DescriptorName')]},
        'source_url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
    }


def supplement(config, today, known_pmids):
    """One recent search over the existing topics and monitored journals."""
    since = max(dt.date.fromisoformat(config['coverage_start']), today - dt.timedelta(days=6))
    recent = f'{since:%Y/%m/%d}:{today:%Y/%m/%d}'
    coverage = config['coverage_start'].replace('-', '/')
    journals = {issn for journal in config.get('monitored_journals', [])
                for issn in [journal['issn'], *journal.get('other_issns', [])]}
    # The journal sweep also covers the two journal-restricted topics.
    clauses = []
    for topic in config['topics']:
        if topic.get('monitored_only'):
            continue
        groups = ['(' + ' OR '.join(f'"{term}"[tiab]' for term in group) + ')'
                  for group in topic['required_term_groups']]
        clauses.append('(' + ' AND '.join(groups) + ')')
    if journals:
        clauses.append('(' + ' OR '.join(f'"{issn}"[issn]' for issn in sorted(journals)) + ')')
    query = f'({" OR ".join(clauses)}) AND {coverage}:{today:%Y/%m/%d}[dp] AND ({recent}[edat] OR {recent}[dp])'
    result = json.loads(request('esearch', term=query, retmode='json', retmax=9999))['esearchresult']
    ids = [pmid for pmid in dict.fromkeys(result['idlist']) if pmid not in known_pmids]
    rows = []
    for offset in range(0, len(ids), 150):
        try:
            xml = ET.fromstring(request('efetch', id=','.join(ids[offset:offset+150]), retmode='xml'))
            if xml.tag != 'PubmedArticleSet':
                raise ValueError(f'Unexpected PubMed EFetch response: {xml.tag}')
        except (OSError, ValueError, ET.ParseError) as exc:
            if not rows:
                raise
            print(f'PubMed metadata retrieval stopped after {len(rows)} records: {exc}', flush=True)
            break
        rows.extend(row for record in xml.findall('PubmedArticle') if (row := article_row(record)))
    return rows, {'topic': 'pubmed-supplement', 'provider': 'PubMed', 'query': query,
                  'candidate_count': int(result['count']), 'retrieved_candidate_count': len(rows),
                  'known_pmid_count': len(result['idlist'])-len(ids)}
