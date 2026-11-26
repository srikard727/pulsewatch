from unittest.mock import patch
import pytest
from main import validate_target, probe, MonitorInput

def test_private_target():
    with pytest.raises(ValueError): validate_target('http://127.0.0.1')
def test_interval_validation():
    with pytest.raises(ValueError): MonitorInput(name='x',url='https://example.com',interval=1)
def test_probe_failure():
    with patch('main.validate_target',side_effect=ValueError):
        result=probe('http://localhost',0)
    assert result['error']=='ValueError' and result['status'] is None
