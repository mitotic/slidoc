#!/usr/bin/env python

'''
Filter Markdown files.

'''

from __future__ import print_function

import os
import re
import sys

class Parser(object):
    newline_norm_re =  re.compile( r'\r\n|\r')
    indent_strip_re =  re.compile( r'^ {4}', re.MULTILINE)
    annotation_re =    re.compile( r'^Annotation:')
    answer_re =        re.compile( r'^(Answer|Ans):')
    concepts_re =      re.compile( r'^Concepts:')
    inline_math_re =   re.compile(r"^`\$(.+?)\$`")
    notes_re =         re.compile( r'^Notes:')

    rules_re = [ ('fenced',            re.compile( r'^ *(`{3,}|~{3,}) *(\S+)? *\n'
                                                   r'([\s\S]+?)\s*'
                                                   r'\1 *(?:\n+|$)' ) ),
                 ('indented',          re.compile( r'^( {4}[^\n]+\n*)+') ),
                 ('block_math',        re.compile( r'^\$\$(.*?)\$\$', re.DOTALL) ),
                 ('latex_environment', re.compile( r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                   re.DOTALL) ),
                 ('hrule',      re.compile( r'^([-]{3,}) *(?:\n+|$)') ) ]

    def __init__(self, cmd_args):
        self.cmd_args = cmd_args
        self.cells_buffer = []
        self.buffered_lines = []
        self.output = []
        self.skipping_notes = False

    def clear_buffer(self):
        if not self.buffered_lines:
            return
        self.markdown('\n'.join(self.buffered_lines)+'\n')
        self.buffered_lines = []

    def parse(self, content):
        content = self.newline_norm_re.sub('\n', content) # Normalize newlines

        while content:
            matched = None
            for rule_name, rule_re in self.rules_re:
                if rule_name == 'indented' and not self.cmd_args.fence:
                    # Do not parse indented code, unless fencing
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
                    if not self.cmd_args.nocode:
                        if self.cmd_args.unfence:
                            self.output.append( re.sub(r'(^|\n)(.)', '\g<1>    \g<2>', matched.group(3))+'\n\n' )
                        else:
                            self.output.append(matched.group(0))

                elif rule_name == 'indented':
                    fenced_code = "```\n" + re.sub(r'(^|\n) {4}', '\g<1>', matched.group(0)) + "```\n\n"
                    self.output.append(fenced_code)

                elif rule_name == 'block_math':
                    if not self.cmd_args.nomarkup:
                        if self.cmd_args.backtick_on:
                            self.output.append("`"+matched.group(0)+"`")
                        else:
                            self.output.append(matched.group(0))

                elif rule_name == 'latex_environment':
                    if not self.cmd_args.nomarkup:
                        self.output.append(matched.group(0))

                elif rule_name == 'hrule':
                    self.hrule(matched.group(1))
                else:
                    raise Exception('Unknown rule: '+rule_name)

            elif '\n' in content:
                line, _, content = content.partition('\n')
                if self.skipping_notes:
                    pass
                elif self.annotation_re.match(line) and not self.cmd_args.keep_annotation:
                    pass
                elif self.answer_re.match(line) and self.cmd_args.noanswers:
                    pass
                elif self.concepts_re.match(line) and self.cmd_args.noconcepts:
                    pass
                elif self.notes_re.match(line) and self.cmd_args.nonotes:
                    self.skipping_notes = True
                else:
                    if self.cmd_args.backtick_off:
                        line = re.sub(r"(^|[^`])`\$(.+?)\$`", r"\1$\2$", line)
                    self.buffered_lines.append(line)

            else:
                self.markdown(content)
                content = ''

        self.clear_buffer()
        return ''.join(self.output)


    def hrule(self, text):
        if not self.cmd_args.norule and not self.cmd_args.nomarkup:
            self.buffered_lines.append(text+'\n')
        self.skipping_notes = False

    def markdown(self, content):
        if not self.cmd_args.nomarkup:
            self.output.append(content)

class Dummy(object):
    pass

Defaults = Dummy()
for argname in ('backtick_off', 'backtick_on', 'fence', 'keep_annotation', 'noanswers', 'nocode', 'noconcepts', 'nomarkup', 'nonotes', 'norule', 'unfence'):
    setattr(Defaults, argname, False)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert from Markdown to Markdown')
    parser.add_argument('--backtick_off', help='Remove backticks bracketing inline math', action="store_true")
    parser.add_argument('--backtick_on', help='Wrap block math with backticks', action="store_true")
    parser.add_argument('--fence', help='Convert indented code blocks to fenced blocks', action="store_true")
    parser.add_argument('--keep_annotation', help='Keep annotation', action="store_true")
    parser.add_argument('--noanswers', help='Remove all Answers', action="store_true")
    parser.add_argument('--nocode', help='Remove all fenced code', action="store_true")
    parser.add_argument('--noconcepts', help='Remove Concepts list', action="store_true")
    parser.add_argument('--nomarkup', help='Retain blocks only', action="store_true")
    parser.add_argument('--nonotes', help='Remove notes', action="store_true")
    parser.add_argument('--norule', help='Suppress horizontal rule separating slides', action="store_true")
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('--unfence', help='Convert fenced code block to indented blocks', action="store_true")
    parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    md_parser = Parser(cmd_args)

    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if os.path.exists(fcomp[0]+'-filtered.md') and not cmd_args.overwrite:
            sys.exit("File %s-filtered.md already exists. Delete it or specify --overwrite" % fcomp[0])

    for j, f in enumerate(cmd_args.file):
        md_text = f.read()
        f.close()
        filtered_text = md_parser.parse(md_text)

        outname = fnames[j]+"-filtered.md"
        outfile = open(outname, "w")
        outfile.write(filtered_text)
        outfile.close()
        print("Created ", outname, file=sys.stderr)
            
