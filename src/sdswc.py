#!/usr/bin/env python

'''
SWC/Jekyll Markdown pre-processor for slidoc
'''

from __future__ import print_function

import argparse
import datetime
import os
import re
import StringIO
import sys
import yaml

BLOCK_PREFIX = '> '

class SWCEpisode(object):
    choice_answer_re = re.compile(r'(([Aa]nswer(\s+is)?|[Ss]olution(\s+is)?|[Oo]ption)\s+)(\d)\b')
    def __init__(self, filename='', options='', site_name='', lesson_name='', orig_lesson_name=''):
        self.filename = filename
        self.options = options
        self.site_name = site_name
        self.lesson_name = lesson_name
        self.orig_lesson_name = orig_lesson_name
        self.nest_level = 0
        self.yaml_block = []
        self.fenced_block = []
        self.in_fenced_block = ''
        self.in_blocks = []
        self.out_blocks = []
        self.ending_block = ''
        self.nonblank_appended = False
        
    def new_block(self, type='', line=None):
        # Block: index, level, type, style, lines
        block = [len(self.out_blocks), self.nest_level, type, '', []]
        if line is not None:
            block[-1].append(line)
        self.out_blocks.append(block)
        self.in_blocks.append(block)

    def end_block(self, level, style=''):
        self.ending_block = style or 'default'
        self.in_blocks[-1][3] = style
        while self.in_blocks and self.in_blocks[-1][1] > level:
            self.in_blocks.pop()

    def append_fenced_block(self, style=''):
        if style.startswith('.language-'):
            self.fenced_block[0] += style.partition('-')[-1]
        elif style in ('.error', '.output'):
            self.fenced_block[0] += style[1:]
        self.in_blocks[-1][-1] += self.fenced_block
        self.nonblank_appended = True
        self.fenced_block[:] = []
        
    def append_to_block(self, line, new_slide=False):
        if self.ending_block:
            while self.in_blocks:
                self.in_blocks.pop()
        if not self.in_blocks:
            self.new_block()
        if self.nonblank_appended and (new_slide or (self.ending_block and self.ending_block != '.callout')):
            self.in_blocks[-1][-1].append('\n---\n')
            self.nonblank_appended = False

        line = re.sub(r'\(\.\./fig/', '(_files/images/', line)
        line = re.sub(r'"\.\./fig/', '"%s/_files/images/' % ('/'+self.site_name if self.site_name else ''), line)
        self.in_blocks[-1][-1].append(line)

        if line.startswith('---'):
            self.nonblank_appended = False
        elif line.strip():
            self.nonblank_appended = True

        self.ending_block = ''

    def check_choices(self, lines):
        # Return indices of lines starting wiht 1., 2., etc. (in sequence)
        kchoices = []
        for k, x in enumerate(lines):
            if x.strip().startswith(str(1+len(kchoices))+'.'):
                kchoices.append(k)
        return kchoices

    def process_input(self, text):
        buf = StringIO.StringIO(text)

        level = 0
        blank_line = True
        nest_indent = {}
        for j, line in enumerate(buf.readlines()):
            line = line.rstrip('\r\n')
            prev_blank = blank_line
            blank_line = not line.strip()

            nmatch = re.match(r'^([> ]*>)(.*)$', line)
            if nmatch:
                level = len(nmatch.group(1).replace(' ',''))
                line = nmatch.group(2)
                if level > self.nest_level:
                    nest_indent[level] = len(line) - len(line.lstrip()) if line.lstrip() else 0
                elif nest_indent.get(level) and line.startswith(''.join([' ']*nest_indent[level])):
                    line = line[nest_indent[level]:]
                    
            elif prev_blank or line.startswith('{:'):
                level = 0

            if not self.in_fenced_block:
                if line.startswith('---'):
                    if not j:
                        self.in_fenced_block = line[:3]
                        continue
                elif line.startswith('```') or line.startswith('~~~'):
                    self.in_fenced_block = line[:3]
                    self.fenced_block = ['```']
                    self.nest_level += 1
                    continue

            if self.in_fenced_block:
                if line.startswith(self.in_fenced_block):
                    if self.in_fenced_block != '---':
                        self.fenced_block.append('```')
                    self.in_fenced_block = ''
                else:
                    if self.in_fenced_block == '---':
                        self.yaml_block.append(line)
                    else:
                        self.fenced_block.append(line)
                continue

            if level > self.nest_level:
                self.nest_level = level
                self.new_block('', line=line)

            elif level == self.nest_level:
                new_slide = not level and prev_blank and line.startswith('### ')
                self.append_to_block(line, new_slide=new_slide)

            else: # level < self.nest_level
                self.nest_level = level
                cmatch = re.match(r'^\s*\{:(.*)\}\s*$', line)
                style = ''
                if cmatch:
                    style = cmatch.group(1).strip()
                    line = None

                if not self.in_fenced_block and self.fenced_block:
                    self.append_fenced_block(style)
                else:
                    self.end_block(level, style=style)
                    if line is not None:
                        self.append_to_block(line)


        out_lines = []
        if self.options:
            out_lines += [ '<!--Slidoc: '+self.options+'-->\n' ]

        config = {}
        if self.yaml_block:
            config = yaml.load('\n'.join(self.yaml_block))
            if 'title' in config:
                out_lines.append( '# '+ config['title'].lstrip().lstrip('#') )
            if 'questions' in config or 'objectives' or self.lesson_name:
                if 'questions' in config:
                    out_lines += ['\n*Questions*:'] + ['- '+x for x in config['questions']] + ['']
                if 'objectives' in config:
                    out_lines += ['\n*Objectives*:'] + ['- '+x for x in config['objectives']] + ['']

                if self.lesson_name:
                    out_lines.append( '''
> Use ESCAPE key or square icon (&#9635;) to switch between *slide* and *document* view.

> In document view, use *left/right* arrow to collapse/expand outline view.
''')
                out_lines += ['\n---\n']

        ans_type = ''
        for bindex, block in enumerate(self.out_blocks):
            _, level, btype, bstyle, lines = block
            if not lines:
                continue
            btext = '\n'.join(lines)+'\n'
            ##print("ABCblock", bindex+1, level, btype, bstyle, repr(lines[0]), file=sys.stderr)
            if bindex+1 < len(self.out_blocks):
                _, next_level, next_btype, next_bstyle, next_lines = self.out_blocks[bindex+1]
            else:
                _, next_level, next_btype, next_bstyle, next_lines = '', 0, '', '', []

            if bstyle == '.challenge':
                ans_type = ''
                if next_bstyle == '.solution':
                    ans_type = 'text/x-code'
                    kchoices = self.check_choices(lines)
                    next_kchoices = self.check_choices(next_lines)
                    if len(kchoices) > 1 and (len(kchoices) == len(next_kchoices) or any(self.choice_answer_re.search(line) for line in next_lines)):
                        ans_type = 'choice'
                        for j, kchoice in enumerate(kchoices):
                            lines[kchoice] = '\n'+lines[kchoice].replace(str(1+j)+'.', chr(j+ord('A'))+'..')

                if not '\n'.join(out_lines).rstrip().endswith('---') and not '\n'.join(lines).lstrip().startswith('---'):
                    out_lines += ['\n---\n']

                out_lines += [''] + lines
                if ans_type:
                    out_lines += ['\nAnswer: '+ans_type+'\n']

            elif bstyle == '.solution':
                lines[0] = '\nNotes: *Solution*\n'
                if ans_type == 'choice':
                    for k in range(1,len(lines)):
                        lmatch = self.choice_answer_re.search(lines[k])
                        if lmatch:
                            lines[k] =lines[k].replace(lmatch.group(0), lmatch.group(1)+chr(int(lmatch.group(5))-1+ord('A')))
                out_lines += lines

            elif bstyle == '.callout':
                lines[0] = '> *' + lines[0].strip().strip('#').strip() + '*'
                out_lines += [lines[0]] + ['> '+line for line in lines[1:]]

            else:
                out_lines += lines

        if 'keypoints' in config:
            out_lines += ['\n## Key points'] + ['- '+x for x in config['keypoints']] + ['']

        out_lines += ['''<footer>
<div align="left">
  <h4>
  Copyright &copy; 2016-%s
  <a href="https://software-carpentry.org/">Software Carpentry Foundation</a>
  </h4>
</div>
<div align="right">
  <h4>
  <a href="http://swcarpentry.github.io/%s/%s">Original rendering of lesson</a>
  </h4>
</div>
</footer>
''' % (datetime.date.today().year, self.orig_lesson_name or self.lesson_name, self.filename)]

        out_lines += ['''<style>
body.slidoc-slide-view blockquote {display: none;}
blockquote {opacity: 0.70;}
.slidoc-block-code:not(.slidoc-block-output):not(.slidoc-block-error) { background: #f8f8f8;}
.slidoc-block-output { opacity: 1.0; }
.slidoc-block-error { background: white;}
.slidoc-block-error code { color: #bd2c00;}
.slidoc-toptoggle-header-question { color: #bd2c00;}
.slidoc-slide-question .slidoc-header { color: #bd2c00;}
</style>''']

        return '\n'.join(out_lines) + '\n'

cmd_parser = argparse.ArgumentParser(description='Convert from SWC/Jekyll Markdown to slidoc Markdown ')
cmd_parser.add_argument('-d', '--dest_dir', metavar='DESTDIR', help='Destination directory')
cmd_parser.add_argument('-l', '--lesson', metavar='LESSON', help='Lesson name')
cmd_parser.add_argument('-o', '--options', metavar='OPTIONS', help='Slidoc options')
cmd_parser.add_argument('--overwrite', help='Overwrite output files', action="store_true", default=None)
cmd_parser.add_argument('-p', '--prefix', metavar='PREFIX', help='Output file prefix')
cmd_parser.add_argument('--insert', metavar='FILE', help='Another markdown file to be inserted at start of file')
cmd_parser.add_argument('-s', '--site', metavar='SITE', help='Site name')
cmd_parser.add_argument('file', help='SWC/Jekyll Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

if __name__ == '__main__':
    cmd_args = cmd_parser.parse_args()

    if len(cmd_args.file) > 1 and not cmd_args.prefix:
        sys.exit('Please specify --prefix for output file(s)')

    yaml_re = re.compile(r'^---[\s\S]*---\s*\n')
    out_names = []
    for ifile, f in enumerate(cmd_args.file):
        text = f.read().lstrip()

        fname, fext = os.path.splitext(os.path.basename(f.name))
        fmatch = re.match(r'^(\d+)-.*$', fname)
        if cmd_args.prefix:
            if fmatch:
                out_name = '%s%02d%s' % (cmd_args.prefix, ifile+1, fext)
            else:
                out_name = cmd_args.prefix + '-' + fname + fext
        else:
            out_name = fname + fext

        ymatch = yaml_re.match(text)
        if ymatch:
            yaml_text = ymatch.group(0)
        else:
            yaml_text = ''

        if not ifile and cmd_args.insert:
            with open(cmd_args.insert) as g:
                insert = g.read().lstrip()
                smatch = yaml_re.match(insert)
                if smatch:
                    insert = insert[len(smatch.group(0)):].strip()
                if insert:
                    ## Prefix insert content
                    if yaml_text:
                        text = yaml_text + '## Insert\n\n' + insert + '\n\n---\n\n' + text[len(yaml_text):].lstrip()
                    else:
                        text = insert + '\n\n---\n\n' + text

        if cmd_args.dest_dir:
            out_name = os.path.join(cmd_args.dest_dir, out_name)
            
        if os.path.exists(out_name) and not cmd_args.overwrite:
            sys.exit('sdswc: Please specify --overwrite to overwrite %s' % out_name)

        episode = SWCEpisode(fname, options=cmd_args.options, site_name=cmd_args.site or '', lesson_name=cmd_args.prefix or '', orig_lesson_name=cmd_args.lesson or '')
        out_md = episode.process_input(text)

        with open(out_name, 'w') as h:
            h.write(out_md)
        out_names.append(out_name)

    print('Created files: '+(cmd_args.dest_dir+'/' if cmd_args.dest_dir else '')+','.join(out_names), file=sys.stderr)
