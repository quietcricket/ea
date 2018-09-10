import os
import glob

import livereload
from flask import Flask, Config, Blueprint, render_template, request
from flask_assets import Environment, Bundle
from webassets.filter import get_filter
from jinja2 import nodes, ChoiceLoader, FileSystemLoader
from jinja2.ext import Extension

import ea_utils as utils


ea_config = {
    #: Custom Jinja filters
    'JINJA_FILTERS': [
        "leading_zero",
        "human_number",
        "add_br",
        "format_datetime",
        "format_currency",
        "add_p",
        "format_date",
        "gen_slug",
        "copyright_year",
        "remove_linebreaks",
        "add_http",
        "add_https"
    ],
    #: Add some parameters and functions to jinja context because
    #: the functions behaves differently with each request
    'JINJA_CONTEXT': [
        "relative_years",
        "highlight_link",
        "next_year",
        "random_string"
    ],

    #: Project folder structure
    'FOLDER_STRUCTURE': [
        'static/',
        'static/scss/styles.scss',
        'static/',
        'static/js_src/Main.js',
        'static/images/',
        'static/fonts/',
        'templates/'
    ],

    #: Folders searching for js, scss files
    'JS_FOLDERS': ['static/js_src'],
    'SCSS_FOLDERS': ['static/scss'],
    'TEMPLATES_FOLDERS': ['templates'],

    #: Watch files for livereload
    'LIVERELOAD': [
        'static/scss/*.scss',
        'static/js_src/*.js',
        'templates/*.html'
    ]
}


class EnhancedApp(object):
    """
    Enhanced Flask App with additional jinja filters/function, webassets integration and livereload integration
    """

    def __init__(self, app_name='enhanced-flask-app', config_file=None, js_filters=[], css_filters=[], **flask_kwargs):
        """
        
        """
        config = Config('.', Flask.default_config)
        if config_file:
            config.from_object(config_file)

        self.app = Flask(app_name, **flask_kwargs)
        self.app.config = config

        # Create webassets
        self.assets_env = Environment(self.app)
        self.assets_env.url_expire = True
        self.assets_env.url = '/static'

        # Initialize additional jinja stuff
        self.enhance_jinja(self.app.jinja_env)

        # Flask assets related
        self.js_filters = []
        self.css_filters = []
        self.depends_scss = []

        self.enhance_assets()

    def create_folder_structure(self):
        for f in self.config['folder_structure']:
            _path = f % self.config
            if os.path.exists(_path):
                break
            self._create_path(_path)

    def enhance_jinja(self, env):
        # Activate HTML blocks trimming. Make the HTML look neater
        env.trim_blocks = True
        env.lstrip_blocks = True
        # Add custom tags/blocks
        env.add_extension('ea.RequiredVariablesExtension')

        # Add additional jinja filters
        for k, v in self.config['jinja_filters'].items():
            env.filters[k] = getattr(utils, v)

        for k, v in self.config['jinja_functions'].items():
            env.globals[k] = getattr(utils, v)

        # Initialize jinja context
        @self.app.context_processor
        def gen_jinja_context():
            obj = {}
            for _k, _v in self.config['jinja_context'].items():
                obj[_k] = getattr(utils, _v)
            return obj

        # Add additional path for templates
        self.app.jinja_loader = ChoiceLoader(
            [FileSystemLoader(f) for f in self.config['templates_folders']])

    def enhance_assets(self):
        """
        Add js, css/scss assets to the environment
        :param env:     webassets environment
        :return:
        """

        js_filters = []
        if self.config['filter_jsmin']:
            js_filters = ['jsmin']

        if self.config['filter_babel']:
            js_filters.append(get_filter(
                'babel', presets=self.config['babel_presets']))

        scss_includes = []
        scss_depends = [utils.abs_path(os.path.join(
            folder, '*.scss')) for folder in self.config['scss_folders']]

        for f in self.config['scss_libs']:
            scss_includes.append(self._find_file(
                f, self.config['scss_folders']))

        sass_compiler = get_filter('libsass', includes=scss_includes)

        scss_filters = [sass_compiler]

        if self.config['filter_autoprefixer']:
            scss_filters.append(get_filter(
                'autoprefixer', autoprefixer='autoprefixer-cli', browsers='last 2 version'))

        #: JS assets
        [self.add_js_asset(asset, js_filters)
         for asset in self.config['js_assets']]

        #: CSS assets
        for folder in self.config['scss_folders']:
            for f in os.listdir(folder):
                if f.endswith('scss') and not f.startswith('_'):
                    self.add_css_asset(f, folder, scss_filters, scss_depends)

        asset_groups = self.config['asset_groups']
        for k, v in asset_groups.items():
            css = v.get('css', [])
            if isinstance(css, basestring):
                asset_groups[k]['css'] = [css]
            js = v.get('js', [])
            if isinstance(js, basestring):
                asset_groups[k]['js'] = [js]
            ext = v.get('ext', [])
            if isinstance(ext, basestring):
                asset_groups[k]['ext'] = [ext]
        self.app.jinja_env.globals['asset_groups'] = asset_groups

    def add_js_asset(self, asset, filters):
        name, input_files = asset
        if isinstance(input_files, basestring):
            input_files = [input_files]
        files = []
        for f in input_files:
            if f.find('*') > -1:
                files.extend(sorted(glob.glob(f), reverse=True))
                continue
            files.append(self._find_file(f, self.config['js_folders']))
        output_file = 'js/%s.js' % name
        b = Bundle(files, output=output_file, filters=filters)
        self.assets_env.register(name + '.js', b)

    def add_css_asset(self, filename, folder, filters, depends):
        name = filename[:-5]
        input_file = utils.abs_path(os.path.join(folder, filename))

        output_file = 'css/%s.css' % name
        b = Bundle(input_file, output=output_file,
                   filters=filters, depends=depends)
        self.assets_env.register(name + '.css', b)

    def run_livereload(self, port=8080):
        """
        Create a live reload server
        :param additional_files:    list of file patterns, relative to the project's root
        :return:
        """
        self.app.debug = True
        self.app.jinja_env.globals['livereload'] = True
        self.app.jinja_env.auto_reload = True
        self.create_folder_structure()
        server = livereload.Server(self.app.wsgi_app)
        for f in self.config['livereload_watch_files']:
            server.watch(utils.abs_path(f % self.config))
        server.serve(port=port, host='0.0.0.0')

    def add_error_handlers(self):
        @self.app.errorhandler(410)
        def content_gone(e):
            return render_template('410.html', error=e), 410

        @self.app.errorhandler(403)
        def access_denied(e):
            return render_template('403.html', error=e), 403

        @self.app.errorhandler(404)
        def content_not_found(e):
            if request.path == '/favicon.ico':
                return 'Not found', 404
            return render_template('404.html', error=e), 404

    def _create_path(self, path):
        if os.path.exists(path):
            return
        parent = os.path.abspath(os.path.join(path, os.pardir))
        while not os.path.exists(parent):
            self._create_path(parent)
        # Check if the path is a file
        if path.rfind('.') > path.rfind(os.path.sep):
            open(path, 'w').close()
        else:
            os.mkdir(path)

    def _to_static_path(self, *filenames):
        return os.path.join(utils.abs_path('static'), *filenames)

    def _find_file(self, filename, paths):
        for p in [os.path.join(_p, filename) for _p in paths] + [filename]:
            if os.path.exists(p):
                return utils.abs_path(p)
        raise Exception('File not found:' + filename)


class RequiredVariablesExtension(Extension):
    # a set of names that trigger the extension.
    tags = set(['required'])

    def parse(self, parser):
        # Create a normal With node first
        # Borrowing the codes from parser.py,
        # the only difference is the end tag is `endrequired`
        # instead of `endwith`
        with_node = nodes.With(lineno=next(parser.stream).lineno)
        targets = []
        values = []
        while parser.stream.current.type != 'block_end':
            if targets:
                parser.stream.expect('comma')
            target = parser.parse_assign_target()
            target.set_ctx('param')
            targets.append(target)
            parser.stream.expect('assign')
            values.append(parser.parse_expression())
        with_node.targets = targets
        with_node.values = values
        with_node.body = parser.parse_statements(
            ('name:endrequired',), drop_needle=True)

        # Manually create a If node
        if_node = nodes.If()
        # If only one variable is required, assigned that variable to test if it is empty
        if len(values) == 1:
            test = values[0]
        else:
            # If more than one variables are required, concat them into a And node
            test = nodes.And(left=values[0], right=values[1])
            for i in range(2, len(values)):
                test = nodes.And(left=test, right=values[i])

        if_node.test = test
        # else_ attribute cannot be None
        if_node.else_ = []
        if_node.elif_ = []
        # Assign with_node as the body of the if_node, to nest them
        if_node.body = [with_node]
        return if_node
