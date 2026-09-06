Bug: Agent fabricates patient date of birth during profile creation
Severity: High
Call: transcripts/call-CA2201912fd2d85bba31e1824d7cc1b5bf-schedule.txt at line 10
Details: While creating a "demo patient profile" for a new caller, the agent only
asked for first and last name (lines 6-8). It never asked for a date of birth,
yet immediately followed up with "Your patient profile is set up and I have
your date of birth as July 4th, 2000." The caller never provided this. The
agent is inventing patient data rather than collecting or flagging it as
missing, which is a serious problem for a real patient-intake flow.
