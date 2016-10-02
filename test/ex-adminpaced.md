<!--slidoc-defaults --pace=3 --features=grade_response,share_all -->

# Test admin pacing


<script>
var choices = ['A', 'B', 'C', 'D'];
function randChoice() {return choices[Math.floor(Math.random()*choices.length)];}
var numbers = [7, 33, 42];
function randNumber() {return numbers[Math.floor(Math.random()*numbers.length)];}
var TestScripts = {};
TestScripts._test_user = [
  ['-ready'],
  ['-initSession'],
  ['initSlideView', 0, 5000, 'next'],
  ['nextEvent', 2, 4000, 'finalizeShare'],
  ['autoEvent', 0, 4000, 'choice', ['B', 'Exp']],
  ['answerTally', 3, 3000, 'finalizeShare'],
  ['autoEvent', 0, 3000, 'input', ['42', 'Exp']],
  ['answerTally', 4, 3000, 'finalizeShare'],
  ['autoEvent', 0, 3000, 'input', ['42', 'Exp']],
  ['answerTally', 0, 500, 'end']
  ];
TestScripts.bbb = [
  ['-ready'],
  ['-initSession'],
  ['-initSlideView'],
  ['AdminPacedAdvance', 2, 500, 'choice', [randChoice(), 'Just because ...']],
  ['-answerTally'],
  ['AdminPacedAdvance', 3, 500, 'input', [randNumber(), 'Just because ...']],
  ['-answerTally'],
  ['AdminPacedAdvance', 4, 500, 'input', [randNumber(), 'Just because ...']],
  ['answerTally', 0, 0, 'end']
  ];
TestScripts.ccc = [
  ['-ready'],
  ['-initSession'],
  ['-initSlideView'],
  ['AdminPacedAdvance', 2, 500, 'choice', [randChoice(), 'Not just because ...']],
  ['-answerTally'],
  ['AdminPacedAdvance', 3, 500, 'input', [randNumber(), 'Not just because ...']],
  ['-answerTally'],
  ['AdminPacedAdvance', 4, 500, 'input', [randNumber(), 'Not just because ...']],
  ['answerTally', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

## Sharing choice

Which of these is a gas giant?

A.. Earth

B*.. Saturn

C.. Venus

D.. Mars

Answer: ; explain

---

## Sharing numeric answer

What is the answer to the ultimate question?

Answer: 42 ; explain

---

## Sharing and voting on numeric+explain

What is the answer to the ultimate question?

Answer: 42 ; explain=markdown; weight=1,0,1; vote=show_live


---

## Last slide

End of session
