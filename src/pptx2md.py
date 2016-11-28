#!/usr/bin/env python

"""
Convert .pptx to .md (crudely)

Use blank lines between list elements

If --embed_slides, embed whole slide as an image by default, unless:
 the string 'Answer:' occurs in the text of the slide at the start of a line,
 or the notes portion of the slide begins with 'Slidoc'

If notes portion of the begins with Slidoc:,
    Discard all text in main slide (unless the notes portion begins with Slidoc:(.*)\nSlideText:)
    Any text following Slidoc: on the same line is treated as the default options (for first slide only)
    Use text following Slidoc: line as slide Markdown, allowing clean embedding of images etc.
    Use ![image0](image_name) to embed the slide itself as an image (after saving slides as .png/.jpg/.jpeg)
    Use ![image1](image_name 'height=200') to embed specific image from main slide (can also specify height in title)
    Note: image_name is optional in the above and may be omitted if using a default name derived from the file name.
          If specified, image_name should be unique and should not include the extension.
    Use CONTINUED at end of notes to continue current Slidoc slide into next pptx slide (to embed multiple slide images)

If the second line in notes portion following the Slidoc: line starts with SlideText:, insert all text in the slide there

The first line of text in the slide is used as the title, if it is the only line or if its followed by a blank line.
(To have a slide without a title, split the text into at least two lines.)

"""

from __future__ import print_function

import argparse
import os
import re
import sys
import zipfile


Text_re = re.compile(r'((?<=\<a:t>).*?(?=\</a:t>)|\</a:br>|\</a:p>|\</a:pPr>|\<a:pPr lvl="1"/>|\<a:endParaRPr)')
Media_re = re.compile(r'Target="\.\./media/(image\d+\.\w+)"')
Notes_re = re.compile(r'Target="\.\./notesSlides/(notesSlide\d+\.\w+)"')
Choice_re = re.compile(r'([^\n])(\n[A-P]\.\.)')

def pptx2md(file, filename='', img_dir=None, embed_slides=False, no_titles=False, img_width=720, img_height=540):
    filename = filename or file.name
    fileprefix = os.path.splitext(os.path.basename(filename ))[0]
    if img_dir is None:
        img_dir = fileprefix+'_img'
    file_mtime = os.path.getmtime(filename) if os.path.exists(filename) else 0
    with zipfile.ZipFile(file) as zfile:
        names = set(zfile.namelist())
        slides = []
        for name in names:
            smatch = re.match(r'^ppt/slides/slide(\d+).xml$', name)
            if smatch:
                slide_numstr = smatch.group(1)
                text = []
                images = []
                notes = []
                indent = 0
                for line in zfile.open(name):
                    for tmatch in Text_re.findall(line):
                        if tmatch.startswith('<a:pPr'):
                            indent = 1
                        elif tmatch.startswith('</a:br>') or tmatch.startswith('<a:endParaRPr'):
                            text.append('\n')
                        elif tmatch.startswith('</a:pPr>'):
                            indent = 0
                            text.append('\n')
                        elif tmatch.startswith('</a:p>'):
                            text.append('\n')
                            if indent == 1:
                                indent = 0
                        elif not tmatch.startswith('<a:') and not tmatch.startswith('</a:'):
                            if indent == 1:
                                text.append('\n- ')
                                indent = 2
                            elif indent:
                                text.append('  ')
                            text.append(tmatch)

                rel_name = 'ppt/slides/_rels/slide'+slide_numstr+'.xml.rels'
                if rel_name in names:
                    for line in zfile.open(rel_name):
                        for imatch in Media_re.findall(line):
                            images.append(imatch)
                        for nmatch in Notes_re.findall(line):
                            for nline in zfile.open('ppt/notesSlides/'+nmatch):
                                for tmatch in Text_re.findall(nline):
                                    if tmatch.startswith('</a:p>'):
                                        notes.append('\n')
                                    elif not tmatch.startswith('<a:') and not tmatch.startswith('</a:'):
                                        notes.append(tmatch)
                    
                slides.append( (int(slide_numstr), images, ''.join(text), ''.join(notes)) )

    def copy_image(image_file, image_name=''):
        img_copy = image_name or (fileprefix + '-' + os.path.basename(image_file))
        if img_dir:
            img_copy = img_dir + '/' + img_copy
            if not os.path.exists(img_dir):
                os.makedirs(img_dir)

        if image_file.startswith(fileprefix+'/'):
            # Slide image
            extensions = ('.png', '.jpg', '.jpeg')
            for extn in extensions:
                ipath = ''
                if os.path.exists(image_file+extn):
                    ipath = image_file+extn
                    img_copy += extn
                    break
            if not ipath:
                raise Exception('pptx2md: Slide image file '+image_file+'/'.join(extensions)+' not found! Please export slideshow as images')

            if os.path.getmtime(ipath) < file_mtime:
                raise Exception('pptx2md: Slide image file '+ipath+' older than slide file! Please re-export slideshow as images')

            with open(ipath) as f:
                with open(img_copy, 'w') as g:
                    g.write(f.read())
        else:
            if image_name:
                img_copy += os.path.splitext(image_file)[1]
            with zfile.open('ppt/media/'+image_file) as f:
                with open(img_copy, 'w') as g:
                    g.write(f.read())
        return img_copy

    all_md = []
    first_header = ''
    with zipfile.ZipFile(file) as zfile:
        slides.sort()
        prev_continued = False
        for slide_num, images, text_str, notes_str in slides:
            md_text = []
            slide_image = ('%s/Slide%02d' if len(slides) >= 10 else '%s/Slide%d') % (fileprefix, slide_num)

            # Replace curly quotes with straight quotes (UTF-8 encoded)
            notes_str = notes_str.strip().replace('\342\200\230', "'").replace('\342\200\231', "'")
            text_str = text_str.strip().replace('\342\200\230', "'").replace('\342\200\231', "'")

            notes_str = notes_str.replace('\342\200\234', '"').replace('\342\200\235', '"')
            text_str = text_str.replace('\342\200\234', '"').replace('\342\200\235', '"')

            # Restore angular brackets
            notes_str = notes_str.replace('&lt;', '<').replace('&gt;', '>')
            text_str = text_str.replace('&lt;', '<').replace('&gt;', '>')

            extra_str = ''

            if notes_str.split('\n')[0].isdigit():
                # Strip page number
                notes_str = '\n'.join(notes_str.split('\n')[1:])
            if notes_str.split('\n')[-1].isdigit():
                # Strip page number
                notes_str = '\n'.join(notes_str.split('\n')[:-1])
            notes_str = notes_str.strip()

            if '\nAnswer:' in text_str:
                text_str = Choice_re.sub(r'\1\n\2', text_str)

            smatch = re.match(r'^Slidoc:(.*)(\n|$)', notes_str)
            if notes_str.startswith('Slidoc:'):
                notes_str = notes_str[len('Slidoc:'):]
                head, _, notes_str = notes_str.partition('\n')
                notes_str = notes_str.strip()
                if head.strip():
                    md_text.append('<!--slidoc-defaults '+head.strip()+' -->\n')

                if notes_str.startswith('SlideText:'):
                    # Retain text in slide
                    notes_str = text_str + '\n\n' + notes_str[len('SlideText:'):].strip()
                elif text_str and '\nExtra:' not in notes_str:
                    # Retain text as extra info
                    extra_str = text_str

                text_str, _, notes_str = notes_str.partition('\nNotes:')
                text_str = text_str.strip()
                notes_str = notes_str.strip()

            elif embed_slides and '\nAnswer:' not in text_str:
                # Insert entire slide as image by default
                if text_str and '\nExtra:' not in notes_str:
                    # Retain text as extra info
                    extra_str = text_str
                text_str = '![image0]()\n'

            if text_str.endswith('CONTINUED'):
                text_str = text_str[:-len('CONTINUED')].strip()
                continued = True
            else:
                continued = False

            images_copied = set()
            lines = []
            if text_str:
                lines = text_str.split('\n')
                if re.match(r'^\d+$', lines[0].strip()):
                    # Strip page number
                    lines = lines[1:]

                # Strip leading blank lines
                while lines and not lines[0].strip():
                    lines = lines[1:]

                if not no_titles and not prev_continued and (len(lines) == 1 or (len(lines) > 1 and not lines[1].strip())) and lines[0][0] not in ' #!' and lines[0].strip()[-1] not in '.?:':
                    # Automatic titles (use space in first line to suppress it)
                    if not first_header:
                        first_header = lines[0].strip()
                        md_text.append('# ')
                    else:
                        md_text.append('## ')
                    lines[0] += '\n'

                for line in lines:
                    lmatch = re.match(r'^!\[image(\d+)\]\s*\((.*)\)\s*$', line)
                    if lmatch:
                        # Image
                        img_name = lmatch.group(2).strip()
                        img_params = ''
                        if '"' in img_name or "'" in img_name:
                            if img_name[0] == '"' or img_name[0] == "'":
                                img_params = img_name.strip()
                                img_name = ''
                            elif ' ' in image_name:
                                img_name, _, img_params = img_name.partition(' ')
                                img_params = img_params.strip()
                            if not img_params or (img_params[0] != '"' and img_params[0] != "'"):
                                raise Exception('pptx2md: Slide %d has invalid image file name: %s' % (slide_num, line))
                        image_num = int(lmatch.group(1))
                        images_copied.add(image_num)
                        if image_num == 0:
                            # Slide image: ![image0]()
                            iheight = img_height
                            img_copy = copy_image(slide_image, img_name)
                        else:
                            # Embedded image: ![image1]()
                            iheight = img_height/max(1,len(images))
                            img_copy = copy_image(images[image_num-1], img_name)
                        if not img_params:
                            img_params = "'height=%d'" % iheight
                        md_text.append("\n![image%d](%s %s)\n\n" % (image_num, img_copy, img_params) )
                    else:
                        md_text.append(line+'\n')

            if not images_copied and images:
                # Copy embedded images by default
                iheight = img_height/max(1,len(images))
                md_images = ["\n"]
                for j, image_file in enumerate(images):
                    img_copy = copy_image(image_file)
                    md_images.append("![image%d](%s 'height=%d')\n\n" % (j+1, img_copy, iheight))
                offset = len(md_text)
                for j, md_line in enumerate(md_text):
                    if md_line.startswith('Answer:'):
                        # Insert images before Answer:
                        offset = j
                        break
                md_text = md_text[:offset] + md_images + md_text[offset:]
 
            elif not images_copied and not text_str:
                # No text and no embedded images; copy slide image by default
                iheight = img_height
                img_copy = copy_image(slide_image)
                md_text.append("\n![image%d](%s 'height=%d')\n\n" % (0, img_copy, iheight) )

            md_text.append('\n')
            if not continued:
                if notes_str:
                    nmatch = re.match(r'^\d+', notes_str)
                    if nmatch:
                        notes_str = notes_str[len(nmatch.group(0)):].strip()
                    if notes_str:
                        md_text.append('Notes: '+notes_str+'\n\n')
                if extra_str:
                    md_text.append('Extra: '+extra_str+'\n\n')
                md_text.append('\n---\n')
            md_text.append('\n')
            all_md += md_text
            prev_continued = continued

    return ''.join(all_md)

if __name__ == '__main__':
    cmd_parser = argparse.ArgumentParser(description='Convert from .pptx to Markdown')
    cmd_parser.add_argument('-e', '--embed_slides', help='Embed image of whole slide by default (unless notes start with Slidoc: or Answer: is present)', action="store_true", default=None)
    cmd_parser.add_argument('-n', '--no_titles', help='Do not automatically generate titles', action="store_true", default=None)
    cmd_parser.add_argument('file', help='pptx filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

    cmd_args = cmd_parser.parse_args()

    for file in cmd_args.file:
        md_text = pptx2md(file, embed_slides=cmd_args.embed_slides, no_titles=cmd_args.no_titles)
        outname = os.path.splitext(file.name)[0] + '.md'
        with open(outname, 'w') as f:
            f.write(md_text)
        print('Created '+outname, file=sys.stderr)

        

