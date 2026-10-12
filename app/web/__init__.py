"""Panel webowy: rejestracja wszystkich blueprintów. Brak któregoś modułu (albo błąd importu w jego wnętrzu — brak
zależności, literówka) ma wywrócić start aplikacji, a nie po cichu schować część panelu."""


def register_web(app):
    from .apikeys import bp as apikeys_bp
    from .auth import bp as auth_bp
    from .catalog import bp as catalog_bp
    from .demo import bp as demo_bp
    from .documents import bp as docs_bp
    from .help import bp as help_bp
    from .history import bp as history_bp
    from .templates_views import bp as templates_views_bp

    for bp in (auth_bp, docs_bp, catalog_bp, templates_views_bp, apikeys_bp, history_bp, demo_bp, help_bp):
        app.register_blueprint(bp)
