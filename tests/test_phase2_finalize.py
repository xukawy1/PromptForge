
import tempfile, os
from app.services.prompt_structure_service import PromptStructureService

def test_structure_compare():
    s=PromptStructureService()
    a=s.build_structure("woman")
    b=s.build_structure("woman")
    assert s.compare(a,b)["similarity"]==1.0
