def register_web(app):
    from .auth import bp as auth_bp
    from .documents import bp as docs_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(docs_bp)
    for name in ("catalog", "templates_views", "apikeys", "history", "demo"):
        try:
            module = __import__(f"app.web.{name}", fromlist=["bp"])
        except ModuleNotFoundError:
            continue  # moduły dochodzą w kolejnych zadaniach (15–17)
        app.register_blueprint(module.bp)
