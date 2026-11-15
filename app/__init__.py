def create_app():
    from .app import create_app as application_factory

    return application_factory()
