import html
import re
import os
import markdown
import sqlite3

class MiniFramework:
    def __init__(self, enable_docs=True, docs_format="html"):
        self.routes = []
        self.urls = {}
        self.middlewares = []
        self.db_connections = {}
        self.debug = False
        self.admin_pin = None
        self.log = []
        self.csrf_tokens = {}
        self.enable_docs = enable_docs
        self.docs_format = docs_format
        self.route_docs = {}
        if self.enable_docs:
            self.urls['/docs'] = self.docs_view

    def docs_view(self, ctx):
        if self.docs_format == "markdown":
            content = "# API Documentation\n"
            for path, doc in self.route_docs.items():
                content += f"- **{path}**: {doc}\n"
            html_doc = markdown.markdown(content)
        else:
            html_doc = "<h1>API Documentation</h1><ul>"
            for path, doc in self.route_docs.items():
                html_doc += f"<li><b>{html.escape(path)}</b>: {html.escape(doc)}</li>"
            html_doc += "</ul>"
        return Response(html_doc)

    def add_route(self, path, func, doc=""):
        self.urls[path] = func
        if self.enable_docs:
            self.route_docs[path] = doc

class FormBuilder:
    @staticmethod
    def build(model_class, values=None, errors=None):
        form_html = "<form method='post'>\n"
        values = values or {}
        errors = errors or {}
        for name, (typ, _) in model_class._fields.items():
            input_type = "text" if 'TEXT' in typ.upper() else "number"
            value = html.escape(str(values.get(name, '')))
            error = f"<span style='color:red'>{html.escape(errors.get(name, ''))}</span>" if name in errors else ""
            form_html += f"{name}: <input name='{name}' type='{input_type}' value='{value}'> {error}<br>\n"
        form_html += "<input type='submit'>\n</form>"
        return form_html

    @staticmethod
    def validate(model_class, form):
        errors = {}
        for field in model_class._fields:
            if not form.get(field):
                errors[field] = "Field required"
        return errors

class AutoCRUD:
    @staticmethod
    def register(app, path, model_class):
        list_path = f"{path}/list"
        add_path = f"{path}/add"

        def list_view(ctx):
            db = ctx['db']
            items = model_class.all(db)
            return Response("<ul>" + ''.join(f"<li>{item.__dict__}</li>" for item in items) + "</ul>")

        def add_view(ctx):
            db = ctx['db']
            if ctx['method'].upper() == 'POST':
                form = ctx['form']
                errors = FormBuilder.validate(model_class, form)
                if not errors:
                    obj = model_class(**form)
                    obj.save(db)
                    return Redirect(list_path)
                else:
                    form_html = FormBuilder.build(model_class, form, errors)
                    return Response(form_html)
            else:
                form_html = FormBuilder.build(model_class)
                return Response(form_html)

        app.urls[list_path] = list_view
        app.urls[add_path] = add_view
        if app.enable_docs:
            app.route_docs[list_path] = f"List all {model_class.__name__}"
            app.route_docs[add_path] = f"Add new {model_class.__name__}"

class ModelMeta(type):
    def __new__(cls, name, bases, dct):
        fields = {k: v for k, v in dct.items() if isinstance(v, tuple)}
        dct['_fields'] = fields
        return super().__new__(cls, name, bases, dct)

class Model(metaclass=ModelMeta):
    table = None

    def __init__(self, **kwargs):
        for field in self._fields:
            setattr(self, field, kwargs.get(field))

    @classmethod
    def create_table(cls, db):
        cols = []
        for name, (typ, opt) in cls._fields.items():
            cols.append(f"{name} {typ} {opt}".strip())
        sql = f"CREATE TABLE IF NOT EXISTS {cls.table or cls.__name__.lower()} ({', '.join(cols)})"
        db.execute(sql)
        db.commit()

    def save(self, db):
        cols = ', '.join(self._fields)
        placeholders = ', '.join('?' for _ in self._fields)
        values = tuple(getattr(self, k) for k in self._fields)
        sql = f"INSERT INTO {self.table or self.__class__.__name__.lower()} ({cols}) VALUES ({placeholders})"
        db.execute(sql, values)
        db.commit()

    @classmethod
    def all(cls, db):
        sql = f"SELECT * FROM {cls.table or cls.__name__.lower()}"
        return [cls(**dict(row)) for row in db.execute(sql)]

    @classmethod
    def filter(cls, db, **kwargs):
        keys = list(kwargs.keys())
        conds = [f"{k}=?" for k in keys]
        sql = f"SELECT * FROM {cls.table or cls.__name__.lower()} WHERE {' AND '.join(conds)}"
        return [cls(**dict(row)) for row in db.execute(sql, tuple(kwargs[k] for k in keys))]

class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status = status
        self.headers = headers or [('Content-Type', 'text/html')]

class Redirect(Response):
    def __init__(self, location):
        super().__init__('', 302, [('Location', location)])

class Error(Response):
    def __init__(self, message, status=500):
        super().__init__(f"<h1>Error {status}</h1><p>{html.escape(message)}</p>", status)
