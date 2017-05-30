<!--slidoc-defaults --pace=3 --features=grade_response,share_all -->

# Test team responses

<script>
var choices = ['A', 'B', 'C', 'D'];
function randChoice() {return choices[Math.floor(Math.random()*choices.length)];}
var TestScripts = {};
TestScripts.admin = [
  ['-ready'],
  ['-initSession'],
  ['initSlideView', 0, 5000, 'next'],
  ['nextEvent', 2, 4000, 'finalizeShare'],
  ['autoEvent', 0, 4000, 'choice', ['']],
  ['answerTally', 3, 4000, 'finalizeShare'],
  ['autoEvent', 0, 1000, 'choice', ['B', 'ANS']],
  ['answerTally', 0, 500, 'next'],
  ['nextEvent', 4, 500, 'end']
  ];
TestScripts.bbb = [
  ['-ready'],
  ['-initSession'],
  ['-initSlideView'],
  ['AdminPacedAdvance', 2, 500, 'choiceSel', ['C']],
  ['-AdminPacedAdvance'],
  ['answerTally', 0, 0, 'end']
  ];
TestScripts.ccc = [
  ['-ready'],
  ['-initSession'],
  ['-initSlideView'],
  ['AdminPacedAdvance', 2, 500, 'choiceSel', ['C']],
  ['-answerTally'],
  ['AdminPacedAdvance', 3, 500, 'choice', [randChoice(), 'Just because ...']]
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

Select your team:

A.. Team A

B.. Team B

C.. Team C

Answer: choice; team=setup

---

Which of these planets is a gas giant?

A.. Earth

B*.. Saturn

C.. Venus

D.. Mars

Answer: ; team=response; explain

---

## Last slide

End of session
