# Research intake in Case 360 Beta

Case Finder Search, Lists and SQL stay available. The English-language beta remains an additional navigation entry. Existing requests and results remain in local history.

1. Describe the study and attach PDF, DOCX, TXT/Markdown or PNG/JPEG files. Use **Add meeting notes** for pasted notes with an optional meeting date and source reference.
2. Review each source's extracted text. Check image OCR, transcribe missing text or exclude the source. Download the unchanged original at any time. Scanned PDF pages and embedded document images may require manual transcription. Links are retained as references; their content is not fetched.
3. Select **Analyze request**. The agent reads relevant source passages and returns shared questions, proposed decisions and a scope summary. Meeting suggestions need analyst acceptance; they do not silently override the original request.
4. Switch between **Researcher** and **Analyst** wording. Answers share the same record and save locally. Add case-specific questions, edit wording, leave partial answers pending or mark questions not applicable with a reason. **Export researcher questions** creates a local text document without the analyst fields; it does not send messages.
5. Review and edit the cohort, inclusion/exclusion, institution and facility, date bounds, variables, measurement windows, grain, counting rules and deliverables. Resolve assumptions and review cited meeting decisions. **Confirm summary and build SQL** creates a new version. Candidate mappings are available in analyst details.

Analysis and generation use the configured request budget across revisions. The SQL is drafted and checked with dry runs, not executed. A changed scope invalidates the current presentation of earlier SQL/checks; those saved results remain in history. A failed connection can retry its frozen inputs without creating another analysis revision.

Originals, extraction and partial work stay local until deleted through **History and clean data**. Reopening a request imports prior answers into the intake view without rewriting its saved result. This iteration does not add a background queue, voice, automatic Granola/MedBox sync or cross-case sharing.

The frontend and private engine protocol must be upgraded together. The companion engine change is on `alvaro/case360-intake-sources` in `susom/dataservices_case360`; installation is a separate release action.
