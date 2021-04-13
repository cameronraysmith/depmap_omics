import re
from depmapomics.test.config import FILE_ATTRIBUTES, TEMP_VIRTUAL_TAIGA_ID, TEMP_VIRTUAL_TAIGA_VERSION
from taigapy import TaigaClient
import numpy as np
tc = TaigaClient()
import pytest

@pytest.fixture(scope='module')
def data(request):
    return tc.get(name=TEMP_VIRTUAL_TAIGA_ID, file=request.param, version=TEMP_VIRTUAL_TAIGA_VERSION)

PARAMS_test_symbol_and_entrezid_in_column = [x['file'] for x in FILE_ATTRIBUTES if x['ismatrix'] and x['gene_id']=='entrez']
@pytest.mark.parametrize('data', PARAMS_test_symbol_and_entrezid_in_column, indirect=['data'])
def test_symbol_and_entrezid_in_column(data):
    matches = data.columns.map(lambda x: re.match(r'([a-zA-Z0-9-_/.]+)\s\((\d+)\)$', x))
    assert  matches.notnull().all(), \
        'some columns do not follow the symbol (entrez id) format. The first few are: \n{}'.format(data.columns[matches.isnull()][:20])


PARAMS_test_symbol_and_enstid_in_column = [x['file'] for x in FILE_ATTRIBUTES if x['ismatrix'] and x['gene_id']=='enst']
@pytest.mark.parametrize('data', PARAMS_test_symbol_and_enstid_in_column, indirect=['data'])
def test_symbol_and_enstid_in_column(data):
    p1 = r'(?:[a-zA-Z0-9-_/.]+)' # only gene symbol
    p2 = r'ENST(?:\d{11})' # only ensembl transcript id
    p3 = p1 + r'\s\(' + p2 + r'\)' # gene symbol (ensembl id)
    p4 = r'ERCC-(?:\d{5})' # ERCC
    p  = '|'.join([p2, p3, p4])
    matches = data.columns.map(lambda x: re.fullmatch(p, x))
    assert  matches.notnull().all(), \
        'some columns do not follow the symbol (ensembl transcript id) format. The first few are: \n{}'.format(data.columns[matches.isnull()][:20])


PARAMS_test_symbol_and_ensgid_in_column = [x['file'] for x in FILE_ATTRIBUTES if x['ismatrix'] and x['gene_id']=='ensg']
@pytest.mark.parametrize('data', PARAMS_test_symbol_and_ensgid_in_column,
        indirect=['data'])
def test_symbol_and_ensgid_in_column(data):
    p1 = r'(?:[a-zA-Z0-9-_/.]+)' # only gene symbol
    p2 = r'ENSG(?:\d{11})' # only ensembl gene id
    p3 = p1 + r'\s\(' + p2 + r'\)' # gene symbol (ensembl id)
    p4 = r'ERCC-(?:\d{5})' # ERCC
    p  = '|'.join([p2, p3, p4])
    matches = data.columns.map(lambda x: re.fullmatch(p, x))
    assert  matches.notnull().all(), \
        'some columns do not follow the symbol (ensembl gene id) format. The first few are: \n{}'.format(data.columns[matches.isnull()][:20])

PARAMS_test_arxspan_ids = [x['file'] for x in FILE_ATTRIBUTES if not x['ismatrix']]
@pytest.mark.parametrize('data', PARAMS_test_arxspan_ids,
                        indirect=['data'])
def test_arxspan_ids(data):
    assert 'DepMap_ID' in data.columns, 'no DepMap_ID column found'
    column = data['DepMap_ID']
    matches = column.map(lambda x: re.match(r'ACH-[\d]{6}$', x))
    assert  matches.notnull().all(), \
        'some rows do not follow the ACH-xxxxxx format. The first few are: \n{}'.format(column.index[matches.isnull()][:20])

PARAMS_test_null_values = [pytest.param(x['file'], marks=pytest.mark.xfail) if x['hasNA'] else x['file']  for x in FILE_ATTRIBUTES if x['ismatrix']]
@pytest.mark.parametrize('data', PARAMS_test_null_values, indirect=['data'])
def test_null_values(data):
    data.notnull().all().all(), 'null values identified in the matrix'

PARAMS_test_matrix_datatypes = [x['file'] for x in FILE_ATTRIBUTES if x['ismatrix']]
@pytest.mark.parametrize('data', PARAMS_test_matrix_datatypes, indirect=['data'])
def test_matrix_datatypes(data):
    datatypes = set(data.dtypes)
    assert len(datatypes) == 1
    assert list(datatypes)[0] == np.dtype('float64')

@pytest.mark.xfail(strict=True)
def test_logtransform(file='CCLE_expression_full', temp_virtual_taiga_id=TEMP_VIRTUAL_TAIGA_ID, version=TEMP_VIRTUAL_TAIGA_VERSION):
    CCLE_expression_full = tc.get(name=temp_virtual_taiga_id, version=version, file=file)
    assert CCLE_expression_full.min().min() == 0
    assert not CCLE_expression_full.sum(axis=1).map(lambda x: np.isclose(x, 1e6, rtol=1e-4)).all(), 'expression data is not log-transformed'

if __name__ == '__main__':
    # print([pytest.param(x['file'], marks=pytest.mark.xfail) if x['hasNA'] else x['file']  for x in FILE_ATTRIBUTES if x['ismatrix']])
    pass
