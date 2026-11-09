# TESSter

NASA's TESS satellite looks for small, regular dips in starlight that may mean a planet is passing in front of a star. Of over 8,000 candidates found so far, only a third have been resolved, and half of those were not planets. Often it was two stars eclipsing each other, or light from a nearby star mixed into the same pixels. Checking a candidate takes data from several archives and knowledge that most students and amateur astronomers do not have.

We want to build an AI agent that automates this process. Given a candidate's number, the agent first checks exoplanet catalogs and recent scientific papers to see if the object has already been confirmed, ruled out, or discussed by other researchers. Next, it collects the data and picks the tests that fit that star. For example, if a bright star sits right next to it, the agent first checks where the signal comes from. It then says whether the signal looks like a planet, a false positive, or whether the data are not enough to tell, and shows what its answer is based on.

The user can ask follow-up questions or check several candidates at once. The agent does not confirm planets, which needs new observations, but it helps choose which candidates to observe.
