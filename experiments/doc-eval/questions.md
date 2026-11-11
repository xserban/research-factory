Q1. Which file in the platform folds the event `screening.decision_recorded` into the SQLite index, and into which table?
Q2. You add a new index table. What must you change so that (a) the index is rebuilt and (b) the state hash of logs written before the table existed stays the same?
Q3. Where is an agent's skill reference (`skill` in an event's actor) computed, and what is its format?
Q4. Which gate does releasing a draft pass, and who may pass it by default in `pilot` mode? Name the file that sets that default.
Q5. Which stage module owns the index table `label_sessions`, and which other projection also writes to it?
Q6. What is the default lease of a task handed to an agent, and where is it defined?
Q7. Under which conditions does the index perform a full rebuild instead of an incremental fold? Name the function.
Q8. Which function does every decision-gate service call before acting, and in which file?
Q9. Which MCP tool serves the next title/abstract screening batch, and which service module implements it?
Q10. Where are held-out seed identifiers scrubbed from answers given to agents? Name the module, the function, and where the MCP layer applies it.
Q11. Which converter is the chosen one for PDFs, and in which file is the per-format choice declared?
Q12. Which payload model class validates the event `protocol.amended`, and in which module is it?
Q13. Which skill should a new agent session on a project start with, and which MCP tool does it call first?
Q14. In which module is the stable `rf:` work identifier built? Name the function.
Q15. Which tests check that a hand-written event failing a guard changes nothing in the index?
