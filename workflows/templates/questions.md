# Questions before the design

Ask these one at a time, in this order. Short answers are fine. Ask one follow-up when an answer
is too vague to design from. If nothing new is stored, questions 3 and 4 take one answer: nothing new.
Don't suggest answers or options: the person thinks first, and the design comes later.

1. What are we building, in one or two sentences, and what are we leaving out?
2. What is the starting point: something new, or a change to something that exists? Which
   screens, APIs and tables will we reuse?
3. What do we need to save: a new table, new columns or a JSON field? Why that choice?
4. How will it be looked up most often, and how much will there be: hundreds, thousands or
   millions of rows?
5. What can go wrong, and what should happen each time? Think of rules not met, and of the system
   misbehaving: two users at once, a slow dependency, bad input.
