
from app.services.prompt_structure_service import PromptStructureService

def test_dna():
    s=PromptStructureService()
    x=s.build_structure("young woman, Tokyo street, 85mm lens, cinematic lighting")
    d=s.dna(x)
    assert d["version"]==1
    assert d["hash"]
    assert d["slot_count"]>=1

def test_compare():
    s=PromptStructureService()
    a=s.build_structure("woman")
    b=s.build_structure("woman")
    assert s.compare(a,b)["similarity"]==1.0
