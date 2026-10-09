"""Local VAF Marketing Intelligence dashboard. Run: streamlit run dashboard.py"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from retry_analysis import retry

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/"data"/"runs"
st.set_page_config(page_title="VAF | Marketing Intelligence",page_icon="◈",layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=DM+Sans:wght@400;500;700&display=swap');
[data-testid="stAppViewContainer"]{background:#f5f7fc;color:#1b2946;font-family:'DM Sans',sans-serif}
[data-testid="stSidebar"]{background:#142349}
[data-testid="stSidebar"] *{color:#ecf2ff!important}
[data-testid="stSidebar"] input{color:#1b2946!important}
h1,h2,h3{font-family:'Outfit',sans-serif;letter-spacing:-.03em}
[data-testid="stMetric"]{background:white;border:1px solid #e6eaf2;padding:17px;border-radius:14px;box-shadow:0 5px 25px #26325908}
[data-testid="stMetricValue"]{color:#263d91;font-family:'Outfit',sans-serif}
[data-testid="stMetricLabel"]{color:#71809c}
.vaf-hero{padding:29px 32px;border-radius:18px;color:white;background:linear-gradient(115deg,#112247,#203971,#465bd9);margin-bottom:18px}
.vaf-hero h1{color:white;font-size:2.15rem;margin:6px 0!important}
.vaf-hero p{color:#d6e0fa;margin:0}
.vaf-eyebrow{letter-spacing:.16em;font-weight:700;font-size:.72rem;color:#a8c7ff}
.vaf-panel{background:white;padding:18px 21px;border-radius:14px;border:1px solid #e5eaf3;margin:10px 0}
.vaf-panel strong{color:#202f57}
.vaf-panel small{color:#6c7891}
.stButton>button{border-radius:10px}
.stButton>button[kind="primary"]{background:#465be5;border:0}
</style>
""",unsafe_allow_html=True)

def load(path,default=None):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return default if default is not None else {}

def runs():
    rows=[]
    if RUNS.exists():
        for path in RUNS.glob("*/*/opportunities.json"):
            obj=load(path)
            if isinstance(obj,dict) and "steps" in obj:rows.append((path.parent,obj))
    return sorted(rows,key=lambda row:row[0].name,reverse=True)

def date_fmt(value):
    try:return date.fromisoformat(str(value)).strftime("%d %b %Y")
    except (TypeError,ValueError):return "Unknown"

def status(item):
    val=item.get("deadline_status") or ""
    if "passed" in val:return "Original deadline passed"
    if "future" in val:return "Future original deadline · unverified"
    return "Verification required"

def opp_frame(items):
    return pd.DataFrame([{
        "Title":x.get("title") or "Untitled",
        "Tender reference":x.get("tender_reference") or "—",
        "Issuing authority":x.get("issuing_authority") or "Unknown",
        "Original deadline":date_fmt(x.get("submission_deadline")),
        "Status":status(x),
        "Source PDF":x.get("document_url") or ""
    } for x in items])

all_data=runs()
with st.sidebar:
    st.markdown("## ◈ VAF AI")
    st.caption("MARKETING INTELLIGENCE")
    st.divider()
    if all_data:
        selected=st.selectbox("Pipeline run",list(range(len(all_data))),
            format_func=lambda i:all_data[i][1].get("topic","Topic")+" · "+all_data[i][0].name[:8])
        folder,data=all_data[selected]
    else:
        folder,data=None,{}
        st.info("No saved runs yet.")
    st.divider()
    st.markdown("#### Start new discovery")
    topic=st.text_input("Topic",value="DigiLocker")
    model=st.text_input("Model",value=os.getenv("OLLAMA_MODEL","qwen3:30b"))
    server=st.text_input("Ollama URL",value=os.getenv("OLLAMA_BASE_URL","http://192.168.0.100:11434"))
    pages=st.slider("Max pages",5,50,20)
    documents=st.slider("Max documents",1,10,5)
    if st.button("Start scan",type="primary",use_container_width=True,disabled=not topic.strip()):
        cmd=[sys.executable,str(ROOT/"run_pipeline.py"),"--topic",topic.strip(),
             "--model",model,"--ollama",server,"--max-pages",str(pages),
             "--max-documents",str(documents),"--timeout","1200"]
        log=ROOT/"data"/"pipeline-ui.log"
        log.parent.mkdir(parents=True,exist_ok=True)
        with log.open("ab") as output:
            proc=subprocess.Popen(cmd,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
        st.success("Started background scan, PID "+str(proc.pid)+".")
    if st.button("Refresh runs",use_container_width=True):st.rerun()
    log=ROOT/"data"/"pipeline-ui.log"
    if log.exists():
        with st.expander("Recent scan logs"):
            st.code(log.read_text(encoding="utf-8",errors="replace")[-4500:],language="text")
    st.divider()
    st.caption("Local presentation build · VAF AI")

st.markdown("""<div class="vaf-hero"><div class="vaf-eyebrow">VAF AI / LEAD DISCOVERY</div>
<h1>Government Tender Intelligence</h1>
<p>Source discovery · Document extraction · AI analysis · Opportunity qualification</p></div>""",unsafe_allow_html=True)
if folder is None:
    st.info("Run a scan from the sidebar or execute the existing run_pipeline.py command.")
    st.stop()

steps=data.get("steps") or {}
discovery=steps.get("discovery") or {}
extract=steps.get("extraction") or {}
ai=steps.get("analysis") or {}
cppp=steps.get("cppp_public_listings") or {}
opportunities=data.get("opportunities") or []
issues=data.get("issues") or []
extracted=load(folder/"extracted_tenders.json",{})
docs=extracted.get("documents") or []
listing=load(folder/"cppp_public_listings.json",{})
public=listing.get("matches") or data.get("public_listing_candidates") or []
st.caption("TOPIC: "+str(data.get("topic"))+" · RUN ID: "+folder.name+" · All opportunity statuses require official verification.")
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("Discovered URLs",discovery.get("unique_candidates",0))
m2.metric("Relevant pages",discovery.get("pages_fetched",0))
m3.metric("PDFs extracted",extract.get("documents_extracted",len(docs)))
m4.metric("AI analyses",ai.get("documents_analyzed",len(opportunities)))
m5.metric("CPPP matches",cppp.get("matches",len(public)))

overview,records,queue,official,diagnostics=st.tabs(
    ["Overview","Opportunities","Document queue","Official listings","Diagnostics"])

with overview:
    left,right=st.columns([1.6,1])
    with left:
        st.subheader("Executive summary")
        st.markdown('<div class="vaf-panel"><strong>'+str(len(opportunities))+
                    ' analyzed opportunities</strong><br><small>Research records, not verified open tenders. Check corrigenda and official notices before any bid.</small></div>',unsafe_allow_html=True)
        if docs and not opportunities:
            st.warning(str(len(docs))+" PDFs are extracted, but AI processing did not complete. Open Document queue to retry.")
        for op in opportunities[:5]:
            st.markdown("**"+str(op.get("title","Untitled"))+"**")
            st.caption(str(op.get("tender_reference") or "—")+" · "+status(op)+" · "+date_fmt(op.get("submission_deadline")))
        st.subheader("Pipeline progress")
        stage_rows=[
            {"Stage":"Discovery","Completed":discovery.get("pages_fetched",0),"Unit":"relevant pages"},
            {"Stage":"Downloads","Completed":discovery.get("documents_downloaded",0),"Unit":"documents"},
            {"Stage":"Text extraction","Completed":extract.get("documents_extracted",0),"Unit":"documents"},
            {"Stage":"Ollama analysis","Completed":ai.get("documents_analyzed",0),"Unit":"documents"},
            {"Stage":"CPPP listing checks","Completed":len(public),"Unit":"matches"}
        ]
        st.dataframe(pd.DataFrame(stage_rows),hide_index=True,use_container_width=True)
    with right:
        st.subheader("Quality & coverage")
        st.metric("Reported issues",len(issues))
        st.metric("Documents awaiting analysis",max(0,len(docs)-len(opportunities)))
        st.info("A zero-match CPPP homepage result does not indicate that the tender portal has no relevant opportunities.")
        st.caption("Finished: "+str(data.get("finished_at","—")))

with records:
    st.subheader("Tender intelligence")
    if not opportunities:
        st.info("No analyzed records for this run. Downloaded documents are available under Document queue.")
    else:
        query=st.text_input("Filter by title, reference or authority",placeholder="Find a tender...")
        filtered=[x for x in opportunities if query.casefold() in
                  " ".join(str(x.get(key) or "") for key in ("title","tender_reference","issuing_authority")).casefold()]
        if filtered:
            table=opp_frame(filtered)
            st.dataframe(table,hide_index=True,use_container_width=True,
                         column_config={"Source PDF":st.column_config.LinkColumn("Source PDF")})
            st.download_button("Export CSV",table.to_csv(index=False).encode("utf-8"),"vaf_leads.csv","text/csv")
        for op in filtered:
            with st.expander(str(op.get("title","Untitled"))):
                c1,c2,c3=st.columns(3)
                c1.metric("Published",date_fmt(op.get("publication_date")))
                c2.metric("Original deadline",date_fmt(op.get("submission_deadline")))
                v=op.get("evidence_validation") or {}
                c3.metric("Evidence snippets",str(v.get("matched","?"))+"/"+str(v.get("checked","?")))
                st.markdown("**Scope**")
                st.write(op.get("scope_summary") or "Not extracted")
                st.markdown("**Technical scope**")
                for item in op.get("technical_requirements") or []:st.markdown("- "+str(item))
                st.markdown("**Eligibility**")
                for item in op.get("eligibility_requirements") or []:st.markdown("- "+str(item))
                if op.get("document_url"):st.link_button("View original tender PDF",op["document_url"])
                st.warning("Status must be verified against the official tender details and corrigenda.")
    st.download_button("Export JSON",json.dumps(data,indent=2,ensure_ascii=False),
                       "vaf_opportunities.json","application/json")

with queue:
    st.subheader("Downloaded document queue")
    st.caption("Text extraction is retained even when Ollama analysis times out.")
    if not docs:st.info("There are no extracted PDFs for this run.")
    for doc in docs:
        st.markdown('<div class="vaf-panel"><strong>'+
                    str(doc.get("document_url","Document")).rsplit("/",1)[-1]+
                    '</strong><br><small>'+str(doc.get("page_count",0))+" pages · "+
                    str(doc.get("text_characters",0))+" characters · "+
                    str(doc.get("extraction_status"))+"</small></div>",unsafe_allow_html=True)
        if doc.get("document_url"):st.link_button("Original PDF",doc["document_url"])
    st.markdown("#### Retry incomplete Ollama analysis")
    limit=st.number_input("Timeout per document (seconds)",min_value=120,max_value=3600,value=1200,step=120)
    st.caption("Uses existing extracted text; does not scrape or download again.")
    if st.button("Retry unfinished documents",type="primary",disabled=not docs):
        try:
            with st.spinner("Running Ollama on remaining documents..."):
                updated=retry(folder,model,server,int(limit))
            st.success(str(updated.get("opportunity_count",0))+" analyzed opportunities available.")
            st.rerun()
        except Exception as exc:st.error("Recovery failed: "+str(exc))

with official:
    st.subheader("CPPP public-listing signals")
    st.caption("Only homepage listings are parsed. CAPTCHA-based keyword searches are not automated.")
    if public:st.dataframe(pd.DataFrame(public),hide_index=True,use_container_width=True)
    else:st.info("No relevant notices appeared in the limited public homepage listings.")
    st.link_button("Manual CPPP advanced search",
                   listing.get("captcha_search_url","https://eprocure.gov.in/eprocure/app"))
    st.caption(str(listing.get("coverage_note") or data.get("coverage_note") or ""))

with diagnostics:
    st.subheader("Run diagnostics")
    if issues:st.dataframe(pd.DataFrame(issues),hide_index=True,use_container_width=True)
    else:st.success("No recorded issues.")
    st.json(steps,expanded=False)
    st.code(str(folder),language="text")
    st.download_button("Export issue log",json.dumps(issues,indent=2),"vaf_issues.json","application/json")
