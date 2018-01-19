#!/usr/bin/env python

'''
Filter Markdown files.

'''

from __future__ import print_function

import argparse
import base64
import io
import os
import random
import re
import shlex
import sys
import urllib
import urllib2
import urlparse
import zipfile

from collections import defaultdict, namedtuple, OrderedDict

import mistune

IMAGE_FMT = 'image%02d'

def str_join(*args):
    return ''.join(stringify(*args))

def stringify(*args):
    if len(args) == 1:
        return args[0].encode('utf-8') if isinstance(args[0], unicode) else args[0]
    else:
        return [arg.encode('utf-8') if isinstance(arg, unicode) else arg for arg in args]

def asciify(s):
    # Replace curly quotes with straight quotes (for powerpoint -> ascii)
    if isinstance(s, unicode):
        s = s.replace(u'\u2018', u"'").replace(u'\u2019', u"'")
        s = s.replace(u'\u201c', u'"').replace(u'\u201d', u'"')
    else:
        s = s.replace('\xe2\x80\x98', "'").replace('\xe2\x80\x99', "'")
        s = s.replace('\xe2\x80\x9c', '"').replace('\xe2\x80\x9d', '"')
    return s

def find_non_ascii(s):
    m = re.search(r'[\x00\x80-\xff]', s)
    return 1+m.start() if m else 0

def restore_angular(s):
    # Restore escaped angular brackets (for powerpoint -> ascii)
    return s.replace('&lt;', '<').replace('&gt;', '>')

def read_file(path):
    with open(path) as f:
        return f.read()
    
def write_file(path, *args):
    with open(path, 'w') as f:
        for arg in args:
            f.write(arg)
    
def normalize_text(text, lower=False):
    # Strip leading/trailing spaces, compress multiple space and optionally lowercase
    text = re.sub(r'\s+', ' ', text.strip())
    return text.lower() if lower else text

def ref_key(text):
    # create reference key (compress multiple spaces, and lower-case)
    return normalize_text(text, lower=True)

def make_id_from_text(text):
    """Make safe ID string from string"""
    return urllib.quote(re.sub(r'[^-\w\.]+', '-', text.lower().strip()).strip('-').strip('.'), safe='')

def generate_random_label(id_str=''):
    if id_str:
        return '%04d-%s' % (random.randint(0, 9999), id_str)
    else:
        return '%03d-%04d' % (random.randint(0, 999), random.randint(0, 9999))

def get_url_scheme(url):
    match = re.match(r'^([-a-z]{3,5}):\S*$', url)
    if match:
        return match.group(1)
    return 'abs_path' if url.startswith('/') else 'rel_path'

def quote_pad_title(title, parentheses=False):
    # Quote non-null title and pad left
    if not title:
        return title
    if '"' not in title:
        return ' "'+title+'"'
    elif "'" not in title:
        return " '"+title+"'"
    elif parentheses and '(' not in title and ')' not in title:
        return " ("+title+")"
    return ''

Attr_re_format = r'''\b%s=([^'"\s]+|'[^'\n]*'|"[^"\n]*")'''

def get_html_tag_attr(attr_name, tag_text):
    match = re.search(Attr_re_format % attr_name, tag_text)
    return re.sub(r'''['"<>&]''', '', match.group(1)) if match else ''

def new_img_tag(src, alt, title, classes=[], image_url='', image_dir=''):
    '''Return img tag string, supporting extension of including align/height/width attributes in title string'''
    attrs = ''
    style = ''
    classList = classes[:]
    if title:
        titlecomps = []
        for attrval in shlex.split(title):
            attr, _, value = attrval.partition('=')
            if value.startswith('"'):
                value = value.strip('"')
            if value.startswith("'"):
                value = value.strip("'")

            if attr.startswith('.'):
                classList.append(attr[1:])
            elif attr in ('height', 'width'):
                attrs += ' ' + attr + '=' + value
            elif attr == 'crop':
                if value:
                    style += 'object-fit:cover;object-position:' + ' '.join(value.strip().split(',')) + ';'
            elif attr.startswith('css-'):
                if value:
                    style += attr.partition('-')[-1] + ':' + value + ';'
            else:
                titlecomps.append(attrval)

        title = ' '.join(titlecomps)
        if title.strip():
            attrs += ' title="' + mistune.escape(title.strip(), quote=True) + '"'
        if style:
            attrs += ' style="' + style + '"'

    if get_url_scheme(src) == 'rel_path':
        if image_url:
            src = image_url + src

        elif image_dir and not src.startswith(image_dir+'/'):
            # Ensure relative paths point to image dir
            src = image_dir + '/' + os.path.basename(src)

    if classList:
        attrs += ' class="%s"' % ' '.join(classList)
    return '<img src="%s" alt="%s" %s>' % (src, alt, attrs)

def find_image_path(src, filename='', filedir='', image_dir=''):
    fprefix = filedir+'/' if filedir else ''
    fname = os.path.splitext(filename)[0] if filename else ''
    if os.path.exists(fprefix+src):
        # Found in specified subpath
        return src
    dirname = os.path.dirname(src)
    if dirname == '_images' or image_dir == '_images':
        basename = os.path.basename(src)
        if fname and os.path.exists(fprefix+fname+'_images/'+basename):
            # Found in fname_images/
            return fname+'_images/'+basename
        elif os.path.exists(fprefix+'_images/'+basename):
            # Found in _images/
            return '_images/'+basename
    return None

class Parser(object):
    newline_norm_re =  re.compile( r'\r\n|\r')
    image_renumber_re = re.compile(r'^image\d+\.')
    indent_strip_re =  re.compile( r'^ {4}', re.MULTILINE)
    annotation_re =    re.compile( r'^Annotation:')
    answer_re =        re.compile( r'^Answer:')
    inline_math_re =   re.compile( r'^\\\((.+?)\\\)')
    notes_re =         re.compile( r'^Notes:')
    tags_re =          re.compile( r'^Tags:')
    inline_js1 =       re.compile( r"`=(\w+)\.(\w+)\(\s*(\d*)\s*\);([^`\n]*)`")
    inline_js2 =       re.compile( r"`=(\w+)\.(\w+)\(\s*(\d*)\s*\)`")
    plugin_re =        re.compile( r'^=(\w+)\(([^\n]*)\)\s*(\n\s*\n|\n$|$)')
    ref_re =           re.compile(r'''^ {0,3}\[([^\]]+)\]: +(\S+)( *\(.*\)| *'.*'| *".*")? *$''')
    ref_def_re =  re.compile(r'''(^|\n) {0,3}\[([^\]]+)\]: +(\S+)( *\(.*\)| *'.*'| *".*")? *(?=\n|$)''')

    rules_re = [ ('fenced',            re.compile( r'^ *(`{3,}|~{3,}) *(\S+)? *\n'
                                                   r'([\s\S]+?)\s*'
                                                   r'\1 *(?:\n+|$)' ) ),
                 ('indented',          re.compile( r'^( {4}[^\n]+\n*)+') ),
                 ('backtick_block_math',re.compile( r'^`\\\[(.*?)\\\]`', re.DOTALL) ),  # Must appear before block_math
                 ('block_math',        re.compile( r'^\\\[(.*?)\\\]', re.DOTALL) ),
                 ('backtex_block_math',re.compile( r'^`\$\$(.*?)\$\$`', re.DOTALL) ),
                 ('tex_block_math',    re.compile( r'^\$\$(.*?)\$\$', re.DOTALL) ),
                 ('latex_environment', re.compile( r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                   re.DOTALL) ),
                 ('plugin_definition', re.compile(r'^ {0,3}<script +type="x-slidoc-plugin" *>\s*(\w+)\s*=\s*\{(.*?)\n *(// *\1)? *</script> *(\n|$)',
                                                re.DOTALL)),
                 ('plugin_embed',      re.compile(r'^ {0,3}<script +type="x-slidoc-embed" *>\s*(\w+)\(([^\n]*)\)\s*\n(.*?)\n *</script> *(\n|$)',
                                                re.DOTALL)),
                 ('hrule',      re.compile( r'^([-]{3,}) *(?:\n+|$)') ),
                 ('minirule',   re.compile( r'^(--) *(?:\n+|$)') )
                  ]

    link_re = re.compile(
        r'!?\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\('
        r'''\s*(<)?([\s\S]*?)(?(2)>)(?:\s+['"]([\s\S]*?)['"])?\s*'''
        r'\)'
    )

    reflink_re = re.compile(
        r'!?\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\[([^^\]]*)\]'
    )

    url_re = re.compile(r'''^(https?:\/\/[^\s<]+[^<.,:;"')\]\s])''')
    data_url_re = re.compile(r'^data:([^;]+/[^;]+);base64,(.*)$')

    img_re = re.compile(r'''<img(\s+\w+(=[^'"\s]+|='[^'\n]*'|="[^"\n]*")?)*\s*>''')

    slidoc_choice_re = re.compile(r"^ {0,3}([a-pA-P])\.\. +")
    header_attr_re = re.compile(r'^(\s*#+.*?)(\s*\{\s*#([-.\w]+)(\s+[^\}]*)?\s*\})\s*$')
    internal_ref_re =  re.compile(
        r'\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\{\s*#([^^\}]*)\}'
    )
    
    def __init__(self, cmd_args, images_zipdata=None, files_url=''):
        self.cmd_args = cmd_args
        self.files_url = files_url
        self.arg_check(cmd_args)
        self.images_zipfile = None
        self.images_map = {}
        self.content_zip_bytes = None
        self.content_zip = None
        self.content_image_paths = set()
        if images_zipdata:
            self.images_zipfile = zipfile.ZipFile(io.BytesIO(images_zipdata), 'r')
            self.images_map = dict( (os.path.basename(fpath), fpath) for fpath in self.images_zipfile.namelist() if os.path.basename(fpath))
        if 'zip' in self.cmd_args.images:
            self.content_zip_bytes = io.BytesIO()
            self.content_zip = zipfile.ZipFile(self.content_zip_bytes, 'w')

        self.skipping_notes = False
        self.cells_buffer = []
        self.buffered_markdown = []
        self.output = []
        self.imported_links = {}
        self.imported_defs = OrderedDict()
        self.imported_refs = OrderedDict()
        self.exported_refs = OrderedDict()
        self.image_refs = {}
        self.old_defs = OrderedDict()
        self.new_defs = OrderedDict()
        self.filedir = ''
        self.filename = ''
        self.fname = ''
        self.renumber_count = cmd_args.renumber

    def arg_check(self, arg_set):
        n = 0
        for opt in ('check', 'copy', 'import', 'export'):
            if hasattr(arg_set, opt):
                n += 1
        if n > 1:
            sys.exit('ERROR Only one of check|copy|import|export may be specified for --images')

    def write_content(self, filepath, content, dry_run=False):
        """Write content to file. If file already exists, check its content"""
        if self.content_zip:
            fname = os.path.basename(filepath)
            if self.cmd_args.image_dir:
                zpath = os.path.basename(self.cmd_args.image_dir)+'/'+fname
            else:
                zpath = '_images/'+fname
            self.content_zip.writestr(zpath, content)
            self.content_image_paths.add(zpath)
            return
        fdir = os.path.dirname(filepath)
        if fdir and not os.path.exists(fdir):
            os.mkdir(fdir)
        elif os.path.exists(filepath):
            if content == read_file(filepath):
                return
            if not self.cmd_args.overwrite:
                raise Exception('Error: Specify --overwrite to copy %s' % filepath)
        if not dry_run:
            write_file(filepath, content)

    def get_link_data(self, link, check_only=False, data_url=False):
        ''' Returns (filename, content_type, content)
            content is data URL if data_url, else raw data.
            Returns None for filename on error
        '''
        try:
            filename = ''
            content_type = ''
            content = ''
            url_type = get_url_scheme(link)
            if url_type == 'data':
                # Data URL
                match = self.data_url_re.match(link)
                if not match:
                    raise Exception('Invalid data URL')
                content_type = match.group(1)
                if data_url:
                    content = link
                else:
                    content = base64.b64decode(match.group(2))

            elif url_type.startswith('http'):
                # HTTP URL
                filename = os.path.basename(urlparse.urlsplit(link).path.rstrip('/'))
                request = urllib2.Request(link)
                if check_only:
                    request.get_method = lambda : 'HEAD'
                response = urllib2.urlopen(request)
                content_type = response.info().getheader('Content-Type')
                if not check_only:
                    content = response.read()
                    if data_url:
                        content = ('data:%s;base64,' % content_type) +  base64.b64encode(content)

            elif url_type == 'rel_path':
                # Relative file "URL"
                filename = os.path.basename(link)
                _, extn = os.path.splitext(filename)
                extn = extn.lower()
                if extn in ('.gif', '.jpg', '.jpeg', '.png', '.svg'):
                    content_type = 'image/jpeg' if extn == '.jpg' else 'image/'+extn[1:]
                if self.images_zipfile:
                    if filename in self.images_map:
                        if not check_only:
                            content = self.images_zipfile.read(self.images_map[filename])
                    else:
                        raise Exception('File %s not found in zip archive' % filename)
                else:
                    new_link = find_image_path(link, filename=self.filename, filedir=self.filedir, image_dir=self.cmd_args.image_dir)
                    if not new_link:
                        raise Exception('File %s does not exist' % link)

                    if not check_only:
                        filepath = self.filedir+'/'+new_link if self.filedir else new_link
                        content = read_file(filepath)
                        if data_url:
                            if not content_type:
                                raise Exception('Unknown content type for file %s' % filename)
                            content = ('data:%s;base64,' % content_type) +  base64.b64encode(content)
            else:
                # Other URL type
                pass

            return filename, content_type, content
        except Exception, excp:
            print('ERROR in retrieving link %s: %s' % (link, excp), file=sys.stderr)
            return None, '', ''

    def external_link(self, match):
        orig_content = match.group(0)
        text = match.group(1)
        link = match.group(3)
        title = match.group(4) or ''

        if link.startswith('_files/') and self.files_url:
            link = self.files_url + link[len('_files'):]

        is_image = orig_content.startswith('!')
        if not is_image:
            if link.startswith('#'):
                if link == '#' or link == '##':
                    link += text.strip()
                if self.cmd_args.pandoc:
                    if link.startswith('##'):
                        return '[%s](%s)' % (text, link[1:])
                    elif link.startswith('#'):
                        return '[%s](%s)' % (text, link)
                    return '[%s](%s%s)' % (text, link, quote_pad_title(title))
            return orig_content

        # Link to image
        if title and self.cmd_args.pandoc:
            attrs = []
            for attr in shlex.split(title):
                if attr.startswith('.'):
                    attrs.append(attr)
            for attr in ('height', 'width'):
                value = get_html_tag_attr(attr, ' '+title)
                if value:
                    attrs.append(attr + '=' + value)
            if attrs:
                return orig_content + '{ ' + ' '.join(attrs) + ' }'
            else:
                return orig_content

        url_type = get_url_scheme(link)

        if url_type == 'rel_path' or (url_type.startswith('http') and 'web' in self.cmd_args.images):
            if 'import' in self.cmd_args.images:
                # Check if link has already been imported (with the same title)
                if 'embed' in self.cmd_args.images:
                    filename, new_title, new_link = self.import_link(link, title)
                    if filename is not None:
                        return self.make_img_tag(new_link, text, new_title)
                else:
                    key, new_title, new_link = self.import_ref(link, title)
                    if key:
                        return '![%s][%s]' % (text, key)

            elif 'check' in self.cmd_args.images:
                self.copy_image(text, link, title, check_only=True)

            elif 'copy' in self.cmd_args.images or 'zip' in self.cmd_args.images:
                new_link, new_title = self.copy_image(text, link, title)
                if new_link is not None:
                    if 'embed' in self.cmd_args.images:
                        return self.make_img_tag(new_link, text, new_title)
                    return '![%s](%s%s)' % (text, new_link, quote_pad_title(new_title))

        if 'embed' in self.cmd_args.images:
            # Convert ref to embedded image tag
            return self.make_img_tag(link, text, title)

        return orig_content

    def copy_image(self, text, link, title, check_only=False):
        """Copies image file to destination. Returns (new_link, title) or (None, None) (for copied URLs)"""
        filename, content_type, content = self.get_link_data(link, check_only=check_only, data_url=False)

        if filename is None:
            print('ERROR: Unable to retrieve image %s' % link, file=sys.stderr)
        elif not check_only and not content:
            print('ERROR: No data in image file %s' % link, file=sys.stderr)
        elif content_type and not content_type.startswith('image/'):
            print('ERROR: Link %s does not contain image data (%s)' % (link, content_type), file=sys.stderr)

        elif not check_only:
            url_type = get_url_scheme(link)
            new_link = ''
            if url_type.startswith('http') and 'copy' in self.cmd_args.images:
                _, extn = content_type.split('/')
                newpath = os.path.basename(urlparse.urlsplit(link).path.rstrip('/'))
                if not newpath.endswith('.'+extn):
                    newpath += '.'+extn
                if self.cmd_args.image_dir:
                    newpath = self.cmd_args.image_dir + '/' + newpath

                if newpath.startswith(self.fname + '_images/'):
                    # Special folder: _images
                    new_link = newpath[len(self.fname):]
                else:
                    new_link = newpath

            elif url_type == 'rel_path':
                linkbase = os.path.basename(link)
                if 'gather_images' in self.cmd_args.images:
                    # Copy all images to new destination image directory
                    newpath = linkbase
                    if self.cmd_args.image_dir:
                        newpath = self.cmd_args.image_dir + '/' + newpath
                    if newpath != link:
                        new_link = newpath
                elif self.image_renumber_re.match(linkbase) and self.renumber_count and ('zip' in self.cmd_args.images or self.cmd_args.dest_dir):
                    # Renumber image*.* only if zip or dest_dir is specified
                    newpath = (IMAGE_FMT % self.renumber_count) + os.path.splitext(linkbase)[1]
                    self.renumber_count += 1
                    if self.cmd_args.image_dir:
                        newpath = self.cmd_args.image_dir + '/' + newpath

                    if newpath.startswith(self.fname + '_images/'):
                        # Special folder: _images
                        new_link = newpath[len(self.fname):]
                    else:
                        new_link = newpath
                else:
                    # Preserve relative path when copying
                    newpath = link

            if self.cmd_args.dest_dir:
                newpath = self.cmd_args.dest_dir + '/' + newpath

            try:
                self.write_content(newpath, content)

                ##print('Copied link %s to %s' % (link, newpath), file=sys.stderr)
                if new_link:
                    # Convert URL to local file link
                    return new_link, title
            except Exception, excp:
                print('ERROR in copying link %s to %s: %s' % (link, newpath, excp), file=sys.stderr)

        return None, None

    def ref_link(self, match):
        # Internal reference
        orig_content = match.group(0)
        text = match.group(1)
        if len(match.groups()) < 2:
            key = ref_key(text)
        else:
            key = ref_key(match.group(2) or match.group(1))

        if not orig_content.startswith("!"):
            # Not image
            if not key.startswith('#'):
                return orig_content
            if key == '#' or key == '##':
                key += text.strip()
            if self.cmd_args.pandoc:
                if key.startswith('##'):
                    return '[%s]: %s' % (text, key[1:])
                elif key.startswith('#'):
                    return '[%s]: %s' % (text, key)
                return text
            else:
                return orig_content

        self.image_refs[key] = text

        if 'embed' in self.cmd_args.images:
            # Convert ref to embedded image tag
            if key in self.new_defs:
                link, title = self.new_defs[key]
                return self.make_img_tag(link, text, title)
            elif key in self.old_defs:
                link, title = self.old_defs[key]
                return self.make_img_tag(link, text, title)

        if 'export' in self.cmd_args.images:
            # Convert exported refs to external links
            if key in self.new_defs:
                link, title = self.new_defs[key]
                return '![%s](%s%s)' % (text, link, quote_pad_title(title))

        return orig_content

    def make_img_tag(self, src, alt, title):
        '''Return img tag string, supporting extension of including align/height/width attributes in title string'''
        return new_img_tag(src, alt, title, image_url=self.cmd_args.image_url, image_dir=self.cmd_args.image_dir)
    
    def img_tag(self, match):
        orig_content = match.group(0)

        src = get_html_tag_attr('src', orig_content)
        if not src:
            return orig_content
        url_type = get_url_scheme(src)

        if 'check' in self.cmd_args.images:
            if url_type == 'rel_path' or (url_type.startswith('http') and 'web' in self.cmd_args.images):
                filename, content_type, content = self.get_link_data(src, check_only=True)
                if filename is None:
                    print('ERROR: Unable to retrieve image %s' % src, file=sys.stderr)

        if self.cmd_args.image_url:
            if url_type == 'rel_path':
                new_src = self.cmd_args.image_url + src
                return orig_content.replace(src, new_src)

        elif url_type == 'rel_path' or (url_type.startswith('http') and 'web' in self.cmd_args.images):
            if 'import' in self.cmd_args.images and 'embed' in self.cmd_args.images:
                # Check if link has already been imported (with the same title); if not import it
                filename, new_title, new_link = self.import_link(src, '')
                if filename is not None:
                    return orig_content.replace(src, new_link)   # Data URL
                    
        return orig_content

    def parse(self, content, filepath=''):
        # Return (output_md, zipped_image_data or None, new_image_number (if renumbering) or 0)
        orig_content = content
        if filepath:
            self.filedir = os.path.dirname(os.path.realpath(filepath))
            self.filename = os.path.basename(filepath)
            self.fname = os.path.splitext(self.filename)[0]

        content = self.newline_norm_re.sub('\n', content) # Normalize newlines

        if self.cmd_args.images:
            # Parse all ref definitions first
            for match in self.ref_def_re.finditer(content):
                key = ref_key(match.group(2))
                link = match.group(3)
                title = match.group(4)[2:-1] if match.group(4) else ''

                self.old_defs[key] = (link, title)
                url_type = get_url_scheme(link)
                if 'export' in self.cmd_args.images and url_type == 'data':
                    # Export ref definition
                    _, new_link, new_title = self.export_ref_definition(key, link, title)
                    if new_link:
                        self.new_defs[key] = (new_link, new_title)
                        self.exported_refs[key] = new_link
                elif 'import' in self.cmd_args.images and not url_type != 'data':
                    if url_type == 'rel_path' or (url_type.startswith('http') and 'web' in self.cmd_args.images):
                        # Relative file "URL" or web URL (with web enabled)
                        _, new_title, new_link = self.import_ref(link, title, key=key)
        
        while content:
            matched = None
            for rule_name, rule_re in self.rules_re:
                # Find the first match
                matched = rule_re.match(content)
                if matched:
                    break

            if matched:
                self.process_buffer()

                # Strip out matched text
                content = content[len(matched.group(0)):]

                if rule_name == 'fenced':
                    if 'code' not in self.cmd_args.strip:
                        if self.cmd_args.unfence:
                            self.output.append( re.sub(r'(^|\n)(.)', '\g<1>    \g<2>', matched.group(3))+'\n\n' )
                        else:
                            self.output.append(matched.group(0))

                elif rule_name == 'indented':
                    if self.cmd_args.fence:
                        fenced_code = "```\n" + re.sub(r'(^|\n) {4}', '\g<1>', matched.group(0)) + "```\n\n"
                        self.output.append(fenced_code)
                    else:
                        self.output.append(matched.group(0))

                elif rule_name == 'backtick_block_math':
                    self.math_block(matched.group(0), matched.group(1))

                elif rule_name == 'backtex_block_math':
                    self.math_block(matched.group(0), matched.group(1), tex=True)

                elif rule_name == 'block_math':
                    self.math_block(matched.group(0), matched.group(1))

                elif rule_name == 'tex_block_math':
                    self.math_block(matched.group(0), matched.group(1), tex=True)

                elif rule_name == 'latex_environment':
                    self.math_block(matched.group(0), matched.group(2), latex=True)

                elif rule_name in ('plugin_definition', 'plugin_embed'):
                    self.plugin_block(matched.group(0))

                elif rule_name == 'hrule':
                    self.hrule(matched.group(1))

                elif rule_name == 'minirule':
                    self.minirule(matched.group(1))
                else:
                    raise Exception('Unknown rule: '+rule_name)

            elif '\n' in content:
                # Process next line
                line, _, content = content.partition('\n')
                if self.skipping_notes:
                    pass
                elif self.annotation_re.match(line) and not self.cmd_args.keep_annotation:
                    pass
                elif self.answer_re.match(line) and 'answers' in self.cmd_args.strip:
                    pass
                elif self.tags_re.match(line) and 'tags' in self.cmd_args.strip:
                    pass
                elif self.notes_re.match(line) and 'notes' in self.cmd_args.strip:
                    self.skipping_notes = True
                else:
                    match_ref = self.ref_re.match(line)
                    if match_ref:
                        # Ref def line; process markdown in buffer
                        self.process_buffer()
                        key = ref_key(match_ref.group(1))
                        if key in self.image_refs and 'embed' in self.cmd_args.images:
                            # Embedding image refs; skip definition
                            pass
                        elif key in self.new_defs:
                            # New ref def
                            new_link, new_title = self.new_defs[key]
                            self.buffered_markdown.append('[%s]: %s%s\n' % (key, new_link, quote_pad_title(new_title,parentheses=True)) )
                        else:
                            # Old ref def
                            self.buffered_markdown.append(line+'\n')
                    else:
                        # Normal markdown line
                        if 'extensions' in self.cmd_args.strip:
                            if self.slidoc_choice_re.match(line):
                                # Strip slidoc extension for interactive multiple-choice
                                line = re.sub('\.\.', '.', line, count=1)
                            if not self.cmd_args.pandoc:
                                # Strip slidoc extension for header attributes (Only the # case)
                                line = self.header_attr_re.sub(r'\1', line)
                            # Strip slidoc extension for internal references
                            line = self.internal_ref_re.sub(r'\1', line)

                        if 'extensions' in self.cmd_args.strip or 'plugin' in self.cmd_args.strip:
                            # Strip slidoc extension for inline JS
                            line = self.inline_js1.sub(r'\4', line)
                            line = self.inline_js2.sub(r'', line)

                        if self.cmd_args.backtick_off:
                            line = re.sub(r"(^|[^`])`\\\((.+?)\\\)`", r"\1\(\2\)", line)
                        elif self.cmd_args.backtick_on:
                            line = re.sub(r"(^|[^`])\\\((.+?)\\\)", r"\1`\(\2\)`", line)

                        if self.cmd_args.tex_math or self.cmd_args.pandoc:
                            line = re.sub(r"\\\((.+?)\\\)", r"$\1$", line)
                        elif self.cmd_args.latex_math:
                            line = re.sub(r"(^|[^\\\$])\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)", r"\1\(\2\3\)", line)

                        if self.plugin_re.match(line) and ('extensions' in self.cmd_args.strip or 'plugin' in self.cmd_args.strip):
                            pass
                        else:
                            self.buffered_markdown.append(line+'\n')

            else:
                # Last line (without newline)
                self.buffered_markdown.append(content)
                content = ''

        self.process_buffer()

        for key, new_link in self.exported_refs.items():
            if key not in self.image_refs:
                print('WARNING Exported orphan ref %s as file %s' % (key, new_link), file=sys.stderr)

        if self.imported_defs:
            # Output imported ref definitions
            self.output.append('\n')
            for link, title in self.imported_defs:
                new_key, new_link = self.imported_defs[(link, title)]
                self.output.append('[%s]: %s%s\n' % (new_key, new_link, quote_pad_title(title,parentheses=True)))

        out_md = ''.join(self.output)
        if self.content_zip and self.content_image_paths:
            if 'md' in self.cmd_args.images:
                # Include original content in zipped image file
                self.content_zip.writestr('content.md', orig_content)

            self.content_zip.close()
            return out_md, self.content_zip_bytes.getvalue(), self.renumber_count
        else:
            return out_md, None, self.renumber_count

    def gen_filename(self, content_type=''):
        label = generate_random_label()
        if content_type.startswith('image/'):
            filename = 'image-' + label + '.' + content_type.split('/')[1]
        else:
            filename = 'file-' + label
            if content_type:
                filename += '.' + content_type.split('/')[0]
        return filename

    def import_link(self, link, title=''):
        """Import link as data URL, return (filename, new_title, new_link). On error, return None, None, None"""
        if link in self.imported_links:
            filename, content_type, content = self.imported_links[link]
        else:
            filename, content_type, content = self.get_link_data(link, data_url=True)
            if filename is None:
                return None, None, None

        title_filename = get_html_tag_attr('file', ' '+title)
        filename = filename or title_filename
        if not filename:
            filename = self.gen_filename(content_type)

        file_attr = 'file='+filename
        if not title_filename:
            # Include filename attribute in title
            if not title:
                new_title = file_attr
            else:
                new_title = ' ' + file_attr
        else:
            new_title = title

        self.imported_links[link] = (filename, content_type, content)
        return filename, new_title, content

    def import_ref(self, link, title, key=''):
        """Return (key, new_title, new_link). On error, return None, None, None"""
        filename, new_title, new_link = self.import_link(link)
        if filename is None:
            return None, None, None

        if key:
            new_key = key
        else:
            # Check if link has already been imported (with the same title)
            new_key, new_link = self.imported_defs.get( (link, title), (None, None) )
            if new_key:
                return new_key, new_title, new_link

        if not new_key:
            # Generate new key from filename
            new_key = make_id_from_text(filename)
            suffix = ''
            if new_key in self.imported_refs:
                j = 2
                while new_key+'-'+str(j) in self.imported_refs:
                    j += 1
                new_key += '-' + str(j)

        self.imported_refs[new_key] = (link, title)
        self.imported_defs[(link, title)] = (new_key, new_link)
        print('Imported ref %s as %s' % (link, new_key), file=sys.stderr)
        return new_key, new_title, new_link

    def export_ref_definition(self, key, link, title, dry_run=False):
        """Return (key, new_link, new_title). On error, return None, None, None"""
        try:
            filename, content_type, content = self.get_link_data(link)
            if filename is None or not content_type or not content_type.startswith('image/'):
                raise Exception('Unable to retrieve image %s' % link)

            # Create new link to local file
            new_link = make_id_from_text(filename)
            if title:
                new_link = make_id_from_text(get_html_tag_attr('file', ' '+title)) or new_link

            new_link = new_link or self.gen_filename(content_type=content_type)

            if self.cmd_args.image_dir:
                new_link = self.cmd_args.image_dir+'/'+new_link

            if self.cmd_args.dest_dir:
                fpath = self.cmd_args.dest_dir + '/' + new_link
            else:
                fpath = new_link

            self.write_content(fpath, content, dry_run=dry_run)
            print('Exported ref %s as file %s' % (key, fpath), file=sys.stderr)
            return key, new_link, title
        except Exception, excp:
            print('ERROR in exporting ref %s as file: %s' % (key, excp), file=sys.stderr)
            return None, None, None

    def hrule(self, text):
        if 'rule' not in self.cmd_args.strip and 'markup' not in self.cmd_args.strip:
            self.buffered_markdown.append(text+'\n\n')
        self.skipping_notes = False

    def minirule(self, text):
        if 'rule' not in self.cmd_args.strip and 'markup' not in self.cmd_args.strip:
            self.buffered_markdown.append(text+'\n\n')

    def plugin_block(self, content):
        if 'extensions' in self.cmd_args.strip or 'plugin' in self.cmd_args.strip:
            pass
        else:
            self.output.append(content)

    def math_block(self, content, inner, latex=False, tex=False):
        if 'markup' not in self.cmd_args.strip:
            if self.cmd_args.tex_math or self.cmd_args.pandoc:
                self.output.append(r'$$'+inner+r'$$')
            elif latex:
                self.output.append(content)
            elif self.cmd_args.backtick_on:
                self.output.append(r'`\['+inner+r'\]`')
            elif self.cmd_args.latex_math:
                self.output.append(r'\['+inner+r'\]')
            else:
                self.output.append(content)

    def process_buffer(self):
        if not self.buffered_markdown:
            return
        md_text = ''.join(self.buffered_markdown)
        self.buffered_markdown = []

        md_text = self.link_re.sub(self.external_link, md_text)
        md_text = self.reflink_re.sub(self.ref_link, md_text)
        md_text = self.img_re.sub(self.img_tag, md_text)

        if 'markup' not in self.cmd_args.strip:
            self.output.append(md_text)


class ArgsObj(object):
    def __init__(self, str_args=[], bool_args=[], int_args=[], defaults={}):
        """List of string args, bool args and dictionary of non-null/False defaults"""
        self.str_args = str_args
        self.bool_args = bool_args
        self.int_args = int_args
        self.defaults = defaults

    def create_args(self, *args, **kwargs):
        """Returns a argparse.Namespace object with argument values, optionally initialized from object args[0] (if not None) and updated with kwargs"""
        if args and args[0] is not None:
            arg_vals = dict( [(k, getattr(args[0], k)) for k in self.str_args+self.bool_args+self.int_args] )
        else:
            arg_vals = dict( [(k, '') for k in self.str_args] + [(k, False) for k in self.bool_args] + [(k, 0) for k in self.int_args] )
            arg_vals.update(self.defaults)
        arg_vals.update(kwargs)

        return argparse.Namespace(**arg_vals)

Args_obj = ArgsObj( str_args= ['dest_dir', 'image_dir', 'image_url', 'images', 'strip'],
                    bool_args= ['backtick_off', 'backtick_on', 'fence', 'keep_annotation', 'latex_math',
                                'overwrite', 'pandoc', 'tex_math', 'unfence'],
                    int_args= ['renumber'],
                    defaults= {'image_dir': '_images'})

def make_arg_set(arg_value, arg_all_list):
    """Converts comma-separated argument value to a set, handling 'all', and 'all,but,..' """
    arg_all_set = set(arg_all_list)
    if isinstance(arg_value, set):
        arg_set = arg_value
    else:
        arg_set = set(arg_value.split(',')) if arg_value else set()

    if 'all' in arg_set:
        arg_set.discard('all')
        if 'but' in arg_set:
            arg_set.discard('but')
            arg_set = arg_all_set.copy().difference(arg_set)
        else:
            arg_set = arg_all_set.copy()    
    return arg_set

if __name__ == '__main__':
    import argparse

    strip_all = ['answers', 'code', 'extensions', 'markup', 'notes', 'plugin', 'rule', 'tags']
    
    parser = argparse.ArgumentParser(description='Convert from Markdown to Markdown')
    parser.add_argument('--backtick_off', help='Remove backticks bracketing inline math', action="store_true")
    parser.add_argument('--backtick_on', help='Wrap block math with backticks', action="store_true")
    parser.add_argument('--dest_dir', help="Destination directory for creating files (default:'')", default='')
    parser.add_argument('--fence', help='Convert indented code blocks to fenced blocks', action="store_true")
    parser.add_argument('--image_dir', help='image subdirectory (default: "_images")', default='_images')
    parser.add_argument('--image_url', help='URL prefix for images, including image_dir')
    parser.add_argument('--images', help='images=(check|copy||export|import)[,embed,zip,md,web,pandoc] to process images (check verifies images are accessible; copy copies images to dest_dir; export converts internal images to external; import creates data URLs;embed converts image refs to HTML img tags;zip zips images;md includes content in zipped image file)', default='')
    parser.add_argument('--keep_annotation', help='Keep annotation', action="store_true")
    parser.add_argument('--latex_math', help='Use \\(..\\) and \\[...\\] notation for math', action="store_true")
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('--pandoc', help='Convert to Pandoc markdown', action="store_true")
    parser.add_argument('--renumber', deault=0, help='Start number for renumbering images when copying to zip or dest_dir')
    parser.add_argument('--strip', help='Strip %s|all|all,but,...' % ','.join(strip_all))
    parser.add_argument('--tex_math', help='Use $..$ and $$...$$ notation for math', action="store_true")
    parser.add_argument('--unfence', help='Convert fenced code block to indented blocks', action="store_true")
    parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    if cmd_args.image_url and not cmd_args.image_url.endswith('/'):
        cmd_args.image_url += '/'
    cmd_args.images = set(cmd_args.images.split(',')) if cmd_args.images else set()

    cmd_args.strip = make_arg_set(cmd_args.strip, strip_all)

    md_parser = Parser( Args_obj.create_args(cmd_args) )   # Use args_obj to pass orgs as a consistency check
    
    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if os.path.exists(fcomp[0]+'-modified.md') and not cmd_args.overwrite:
            sys.exit("File %s-modified.md already exists. Delete it or specify --overwrite" % fcomp[0])

    for j, f in enumerate(cmd_args.file):
        filepath = f.name
        md_text = f.read()
        f.close()
        modified_text = md_parser.parse(md_text, filepath)

        outname = fnames[j]+"-modified.md"
        write_file(outname, modified_text)
        print("Created ", outname, file=sys.stderr)
            
