#!/usr/bin/env python

'''
Convert lecture/slides from Jupyter Notebook format to Markdown.

Output image files are saved as external files.

'''

from __future__ import print_function

import base64
import io
import json
import os
import random
import re
import sys
import zipfile

import md2md
import sliauth

Fenced_re = re.compile( r'^ *(`{3,}|~{3,}) *(\S+)? *\n'
                        r'([\s\S]+?)\s*'
                        r'\1 *(?:\n+|$)', re.MULTILINE)
Linestart_re = re.compile(r'(^|\n)')

def unfence(match):
    return Linestart_re.sub('\g<1>    ', match.group(3))+'\n'


def rand_name():
    return '%03d-%04d' % (random.randint(0, 999), random.randint(0, 9999))


class NBParser(object):
    def __init__(self, cmd_args):
        self.cmd_args = cmd_args
        self.content_zip_bytes = None
        self.content_zip = None
        self.content_image_paths = set()
        if self.cmd_args.zip_images:
            self.content_zip_bytes = io.BytesIO()
            self.content_zip = zipfile.ZipFile(self.content_zip_bytes, 'w')
        self.outbuffer = []
        self.defbuffer = []

    def normalize(self, source, nonewline=False):
        if isinstance(source, list):
            source = ''.join(source)
        if not source.endswith('\n') and not nonewline:
            source += '\n'
        return source
        
    def parse(self, nb_dict):
        for j, cell in enumerate(nb_dict['cells']):
            cell_type = cell['cell_type']
            source = self.normalize(cell.get('source', ''))

            if cell_type == 'raw':
                self.outbuffer.append( source )
                    
            elif cell_type == 'markdown':
                if self.outbuffer:
                    self.outbuffer.append('\n\n---\n\n')
                self.outbuffer.append( Fenced_re.sub(unfence, source) )
                    
            elif cell_type == 'code':
                if self.outbuffer:
                    self.outbuffer.append('\n\n---\n\n')
                self.outbuffer.append( '\n```\n' + source + '```\n\n' )

                outputs = cell.get('outputs', [])
                if outputs and self.cmd_args.output_notes:
                    self.outbuffer.append( 'Notes:\n' )
                for output in outputs:
                    output_type = output.get('output_type', '')

                    if output_type == 'stream':
                        if output.get('name') == 'stdout':
                            self.outbuffer.append( '\n```nb_output\n' + self.normalize(output.get('text', '')) + '```\n\n')
                        if output.get('name') == 'stderr':
                            self.outbuffer.append( '\n```nb_error\n' + self.normalize(output.get('text', '')) + '```\n\n')

                    elif output_type in ('display_data', 'execute_result'):
                        data = output['data']
                        data_text = data.get('text/plain', '')
                        alt_text = 'image'
                        if re.match(r'^\s*<matplotlib.figure.Figure .*>\s*$', self.normalize(data_text, nonewline=True)):
                            alt_text = self.normalize(data_text, nonewline=True)
                            data_text = ''
                        if 'image/png' in data:
                            basename = 'nb_output-%s.png' % md2md.generate_random_label()
                            if self.cmd_args.image_dir:
                                img_filename =  self.cmd_args.image_dir + '/' + basename
                            else:
                                img_filename = basename
                            content = base64.b64decode(data['image/png'].strip())
                            if self.content_zip:
                                self.content_zip.writestr(img_filename, content)
                                self.content_image_paths.add(img_filename)
                            else:
                                with open(img_filename, 'wb') as f:
                                    f.write(content)
                                print('Created', img_filename, file=sys.stderr)
                            title = 'nb_output file="%s"' % basename
                            self.outbuffer.append("![%s](%s '%s')\n\n" % (alt_text, img_filename, title) )
                        if data_text:
                            self.outbuffer.append( '\n```nb_output\n' + self.normalize(data_text) + '```\n\n')

        out_str = ''.join(self.outbuffer)
        if self.defbuffer:
            out_str += '\n' + ''.join(self.defbuffer)

        img_data = None
        if self.content_zip and self.content_image_paths:
            # Include original content in zipped images file
            self.content_zip.writestr('content.md', sliauth.str_encode(out_str))
            self.content_zip.close()
            img_data = self.content_zip_bytes.getvalue()

        return out_str, img_data

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert from Jupyter Notebook format to Markdown')
    parser.add_argument('--image_dir', help='image subdirectory (default: "_images")', default='_images')
    parser.add_argument('--output_notes', help='Treat cell output as notes', action="store_true")
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('--zip_images', help='Create zip file with Markdown and images', action="store_true")
    parser.add_argument('file', help='Notebook filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    nb_parser = NBParser(cmd_args)

    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.ipynb':
            sys.exit('Invalid file extension for '+f.name)

        if os.path.exists(fcomp[0]+'.md') and not cmd_args.overwrite:
            sys.exit("File %s.md already exists. Delete it or specify --overwrite" % fcomp[0])

    for j, f in enumerate(cmd_args.file):
        fname = fnames[j]
        nb_dict = json.load(f)
        f.close()
        md_text, img_data = nb_parser.parse(nb_dict)

        if img_data:
            outname = fname+'.zip'
            with open(outname, 'wb') as f:
                f.write(img_data)
        else:
            outname = fname+'.md'
            with open(outname, 'w') as f:
                f.write(md_text)

        print('Created ', outname, file=sys.stderr)
            
