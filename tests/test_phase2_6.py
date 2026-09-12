
def test_services_import():
    from app.services.tag_service import TagService
    from app.services.relationship_service import RelationshipService
    assert TagService and RelationshipService
