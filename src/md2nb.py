#!/usr/bin/env python

'''
Convert lecture/slides from Markdown to Jupyter Notebook format.

Fenced code blocks are converted to notebook code cells, by default.
Optionally, indented code blocks may also be converted to cells.

'''

from __future__ import print_function

import json
import os
import re
import sys

Nb_metadata_format = '''
{
  "metadata": {
  "language_info": {
   "name": "%(lang)s"
  }
 },
  "nbformat": 4,
  "nbformat_minor": 0,
  "cells" : [
%(cells)s
]
}
'''

Markdown_cell_format = '''
{
  "cell_type" : "markdown",
  "metadata" : {},
  "source" : %s
}
'''

Code_cell_format = '''
{
  "cell_type" : "code",
  "execution_count": null,
  "metadata" : {
      "collapsed" : true
  },
  "source" : %s,
  "outputs": [
%s
  ]
}
'''

Output_text_format = '''
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
%s
     ]
    }
'''

Output_img_format = '''
    {
     "data": {
      "image/png": "%s",
      "text/plain": [
       %s
      ]
      },
     "metadata": {},
     "output_type": "display_data"
    }
'''

class MDParser(object):
    newline_norm_re =  re.compile( r'\r\n|\r')
    indent_strip_re =  re.compile( r'^ {4}', re.MULTILINE)
    concepts_re =      re.compile( r'^Concepts:')
    notes_re =         re.compile( r'^Notes:')

    rules_re = [ ('fenced',   re.compile( r'^ *(`{3,}|~{3,}) *(\S+)? *\n'
                                          r'([\s\S]+?)\s*'
                                          r'\1 *(?:\n+|$)' ) ),
                 ('indented', re.compile( r'^( {4}[^\n]+\n*)+') ),
                 ('hrule',    re.compile( r'^([-]{3,}) *(?:\n+|$)') ) ]

    def __init__(self, cmd_args):
        self.cmd_args = cmd_args
        self.cells_buffer = []
        self.buffered_lines = []
        self.skipping_notes = False

    def clear_buffer(self):
        if not self.buffered_lines:
            return
        self.markdown('\n'.join(self.buffered_lines)+'\n')
        self.buffered_lines = []

    def parse_cells(self, content):
        content = self.newline_norm_re.sub('\n', content) # Normalize newlines

        while content:
            matched = None
            for rule_name, rule_re in self.rules_re:
                if rule_name == 'indented' and not self.cmd_args.indented:
                    # Do not 'cellify' indented code, unless requested
                    continue

                # Find the first match
                matched = rule_re.match(content)
                if matched:
                    break

            if matched:
                self.clear_buffer()

                # Strip out matched text
                content = content[len(matched.group(0)):]

                if rule_name == 'fenced':
                    self.code_block(matched.group(3), lang=matched.group(2) )

                elif rule_name == 'indented':
                    self.code_block(self.indent_strip_re.sub('', matched.group(0)) )

                elif rule_name == 'hrule':
                    self.hrule(matched.group(1))
                else:
                    raise Exception('Unknown rule: '+rule_name)

            elif '\n' in content:
                line, _, content = content.partition('\n')
                if self.skipping_notes:
                    pass
                elif self.concepts_re.match(line) and self.cmd_args.noconcepts:
                    pass
                elif self.notes_re.match(line) and self.cmd_args.nonotes:
                    self.skipping_notes = True
                else:
                    self.buffered_lines.append(line)

            else:
                self.markdown(content)
                content = ''

        self.clear_buffer()

        nb_cells = ','.join(self.cells_buffer)
        return Nb_metadata_format % {'lang': 'python', 'cells': nb_cells}


    def hrule(self, text):
        if not self.cmd_args.norule and not self.cmd_args.nomarkup:
            self.buffered_lines.append(text+'\n')
        self.skipping_notes = False

    def code_block(self, code, lang=''):
        outputs = ''
        self.cells_buffer.append(Code_cell_format % (self.split_str(code), outputs))

    def markdown(self, content):
        if not self.cmd_args.nomarkup:
            self.cells_buffer.append(Markdown_cell_format % self.split_str(content))

    def split_str(self, content):
        lines = content.split('\n')
        out_lines = [x+'\n' for x in lines[:-1]]
        if not out_lines or lines[-1]:
            out_lines.append(lines[-1])
        return json.dumps(out_lines)

Nb_convert_url_prefix = 'http://nbviewer.jupyter.org/url/'

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert from Markdown to Jupyter Notebook format')
    parser.add_argument('--href', help='URL prefix for website')
    parser.add_argument('--indented', help='Convert indented code blocks to notebook cells', action="store_true")
    parser.add_argument('--noconcepts', help='Remove Concepts list', action="store_true")
    parser.add_argument('--nomarkup', help='Convert code blocks only', action="store_true")
    parser.add_argument('--nonotes', help='Remove notes', action="store_true")
    parser.add_argument('--norule', help='Suppress horizontal rule separating slides', action="store_true")
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    url_prefix = ''
    if cmd_args.href:
        if cmd_args.href.startswith('http://'):
            url_prefix = cmd_args.href[len('http://'):]
        else:
            url_prefix = cmd_args.href

    md_parser = MDParser(cmd_args)

    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if os.path.exists(fcomp[0]+'.ipynb') and not cmd_args.overwrite:
            sys.exit("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

    flist = []
    for j, f in enumerate(cmd_args.file):
        fname = fnames[j]
        md_text = f.read()
        f.close()
        nb_text = md_parser.parse_cells(md_text)

        flist.append( (fname, '<a href="%s%s%s.ipynb">%s.ipynb</a>' % (Nb_convert_url_prefix, url_prefix, fname, fname)) )
        outname = fname+".ipynb"
        if os.path.exists(outname) and not cmd_args.overwrite:
            print("File %s already exists. Delete it or specify --overwrite" % outname)
            sys.exit(1)
        outfile = open(outname, "w")
        outfile.write(nb_text)
        outfile.close()
        print("Created ", outname, file=sys.stderr)

    if cmd_args.href:
        for fname, flink in flist:
            sys.stdout.write('<ol>\n')
            sys.stdout.write('  <li>%s</li>\n' % flink)
            sys.stdout.write('</ol>\n')
            
