"""Deterministic financial comparison executors. Input: visible cells and question."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
import math
import re
import unicodedata


def clean(x):
    return " ".join(unicodedata.normalize("NFKC",str(x or "")).lower().replace("−","-").replace("–","-").split())


YEAR = r"(?:19|20)\d{2}"
STOP = set("a an the of at to was were is are been did does do for from with on and or between under during as by have has had their there its than that it in which who what when how among within reported fiscal financial year years date ended end amount amounts value values highest higher most greatest greater larger largest maximum max lowest lower less least smallest smaller minimum min fewer fewest more much many thousand thousands million millions billion billions".split())
ALIASES={"revenues":"revenue","costs":"cost","sales":"sale","directors":"director","payables":"payable","receivables":"receivable","amounts":"amount","liabilities":"liability","assets":"asset","shares":"share","activities":"activity","securities":"security","oldest":"age","youngest":"age","percentages":"percent","percentage":"percent","remuneration":"compensation","nonreturning":"non returning"}


def tokens(s):
    words=re.findall(r"[a-z]+|\d+",clean(s))
    return frozenset(ALIASES.get(w,w[:-1] if len(w)>4 and w.endswith("s") and not w.endswith("ss") else w) for w in words if w not in STOP)


def years(s):
    return re.findall(r"(?<!\d)"+YEAR+r"(?!\d)",clean(s))


def period(s):
    s=clean(s)
    match=re.search(r"(?<!\d)("+YEAR+r"\s*[/–-]\s*(?:"+YEAR+r"|\d\d))(?!\d)",s)
    if match:return re.sub(r"\s+","",match[1])
    y=years(s)
    return y[0] if len(y)==1 else ""


def scale(s):
    s=clean(s)
    if re.search(r"\bbillions?\b|[$£€]\s*bn\b",s):return Decimal("1e9")
    if re.search(r"\bmillions?\b|[$£€]\s*m\b",s):return Decimal("1e6")
    if re.search(r"\bthousands?\b|['’]\s*000\b|[$£€]\s*k\b",s):return Decimal("1e3")
    return Decimal(1)


def numeric(s):
    v=clean(s).replace(",","").strip()
    v=re.sub(r"\s*\[\d+\]\s*$","",v)
    if not v:return None
    m=re.fullmatch(r"([$£€]?)\s*(\(?)\s*([$£€]?)\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(%?)\s*(\)?)",v)
    if not m or bool(m[2])!=bool(m[6]):return None
    return (Decimal(m[4])*(-1 if m[2] else 1),m[5] or m[1] or m[3])


def operation(q):
    if re.search(r"\b(?:how (?:many|much)|difference between|by how|change from|on average|ratio of|second (?:highest|lowest)|third (?:highest|lowest))\b",q):
        return None
    gt=r"(?:greater than|higher than|more than|larger than|exceed(?:ed)?|above|at least)"
    lt=r"(?:less than|lower than|below|fewer than|smaller than|at most)"
    m=re.search(r"\b("+gt+"|"+lt+r")\s*([$£€]?)\s*([+-]?[\d,]+(?:\.\d+)?)\s*(%|percent|thousands?|millions?|billions?)?",q)
    if m:
        direction="gt" if re.fullmatch(gt,m[1]) else "lt"
        if m[1] in {"at least","at most"}:direction+="e"
        return direction,Decimal(m[3].replace(",",""))*scale(m[4]),("%" if m[4] in {"percent","%"} else m[2]),bool(scale(m[4])!=1)
    hi=bool(re.search(r"\b(?:most|more|highest|higher|greatest|greater|larger|largest|maximum|oldest|strongest|biggest|longest)\b",q))
    lo=bool(re.search(r"\b(?:least|less|lowest|lower|smaller|smallest|fewest|fewer|minimum|youngest|shortest)\b",q))
    if hi==lo:return None
    return ("max" if hi else "min"),None,"",False


@dataclass
class Member:
    row:int
    col:int
    answer:str
    raw:str
    amount:Decimal
    unit:str
    declared:bool
    attributes:frozenset


@dataclass
class Range:
    title:str
    axis:str
    cue:frozenset
    members:list
    score:float
    answer:str|None
    winners:list


def describe(md,header,local,global_scale):
    val,unit=md
    context=clean(local+" "+header)
    if not unit and re.search(r"%|\b(?:percent|percentage)\b",context):unit="%"
    local_scale=scale(context)
    if unit=="%":return val,unit,True
    if "per share" in context or "earnings per" in context:
        return val,(unit or "number")+"/share",True
    # Explicit local declarations take precedence over the table-wide unit.
    multiplier=local_scale if local_scale!=1 else global_scale
    return val*multiplier,(unit or "number"),bool(multiplier!=1)


def extreme(members,op):
    if len(members)<2:return None,[]
    units={m.unit for m in members}
    # Unmarked values can share one explicit currency (symbols are often sparse).
    units.discard("number")
    if len(units)>1:return None,[]
    direction,target,target_unit,scale_required=op
    if target_unit and units and target_unit not in units:return None,[]
    if scale_required and not all(m.declared for m in members):return None,[]
    if target is None:
        v=(max if direction=="max" else min)(m.amount for m in members)
        ws=[m for m in members if m.amount==v]
    else:
        test={"gt":lambda x:x>target,"gte":lambda x:x>=target,"lt":lambda x:x<target,"lte":lambda x:x<=target}[direction]
        ws=[m for m in members if test(m.amount)]
    answers={clean(m.answer):m.answer for m in ws}
    return next(iter(answers.values())) if len(answers)==1 else None,ws


def make_model(table):
    if not table:return None
    width=max(map(len,table),default=0)
    if width<2:return None
    rows=[list(map(lambda x:str(x or "").strip(),r))+[""]*(width-len(r)) for r in table]
    body=None
    for i,row in enumerate(rows):
        occupied=[x for x in row[1:] if x]
        nums=[x for x in occupied if numeric(x) is not None]
        if not nums:continue
        # A row of four-digit financial years before any observations is a header.
        if all(re.fullmatch(YEAR,clean(x)) for x in nums) and len(nums)==len(occupied) and (len(nums)>=2 or not row[0].strip()):continue
        body=i;break
    if body is None:return None
    hdr=[[] for _ in range(width)]
    leading_sections=[]
    for row in rows[:body]:
        if row[0] and not any(row[1:]):
            leading_sections.append(row[0]);continue
        last=""
        for j in range(1,width):
            if row[j]:last=row[j]
            if last:hdr[j].append(last)
    headers=[" ".join(dict.fromkeys(v)) for v in hdr]
    global_units=[s for r in rows[:body] for s in r if scale(s)!=1]
    distinct={scale(s) for s in global_units}
    global_scale=next(iter(distinct)) if len(distinct)==1 and any(re.search(r"\bin\s+(?:[a-z ]+\s)?(?:thousand|million|billion)",clean(s)) for s in global_units) else Decimal(1)
    # A sparse leading label immediately adjacent to first data row is its parent.
    section=rows[body-1][0] if body and rows[body-1][0] and not any(rows[body-1][1:]) else ""
    data=[]
    for i in range(body,len(rows)):
        row=rows[i]
        if row[0] and not any(row[1:]):section=row[0];continue
        if not row[0] or not any(numeric(x) for x in row[1:]):continue
        data.append((i,row[0],section))
    return rows,headers,data,global_scale


def predict(table,question):
    q=clean(question)
    qt=tokens(q)
    op=operation(q)
    model=make_model(table)
    if not op or not model:return {"base":None,"contrast":None,"flat":None,"trace":{"reason":"unsupported comparison or empty table","ranges":[]}}
    rows,hdr,data,global_scale=model
    qyears=set(years(q))
    want_year=bool(re.search(r"\b(?:which|what)\s+(?:(?:fiscal|calendar|reporting|financial)\s+)?(?:year|period|date)s?\b|\bwhen\b",q))
    labels=[row for _,row,_ in data]+[s for _,_,s in data if s]+[s for s in hdr if s]
    vocabulary=Counter(w for s in labels for w in tokens(s))
    def weight(w):return math.log(1+(len(labels)+1)/(1+vocabulary[w]))
    def fit(ws):
        if not ws:return 0.
        hit=sum(weight(w) for w in ws&qt)
        return hit*(.55+.45*hit/sum(weight(w) for w in ws))
    pool=[];flat=[]
    def push(title,axis,cue,members,prior=0,flat_eligible=False):
        if len(members)<2:return
        ans,winners=extreme(members,op)
        item=Range(title,axis,cue,members,fit(cue)+prior,ans,winners)
        pool.append(item)
        if flat_eligible:flat.append(item)
    def member(r,c,answer,local,section):
        raw=rows[r][c];md=numeric(raw)
        if md is None:return None
        amount,unit,declared=describe(md,hdr[c],local,global_scale)
        return Member(r,c,answer,raw,amount,unit,declared,tokens(section+" "+local+" "+hdr[c]))
    def total(s):return bool(re.match(r"^(?:grand\s+)?(?:total|subtotal)\b",clean(s)))
    component=bool(re.search(r"\b(?:component|category|item|type|segment|region|director|person|employee|country|geograph|class|source|product|activity|line item)\w*\b|\bwho\b",q))
    # Horizontal comparisons: a row names the metric and columns identify members.
    for r,lab,sec in data:
        members=[]
        for c in range(1,len(hdr)):
            yr=period(hdr[c]);name=yr if want_year else hdr[c]
            if not name or (len(qyears)>=2 and yr and not (set(years(yr))&qyears)):continue
            m=member(r,c,name,lab,sec)
            if m:members.append(m)
        if want_year and len(set(x.answer for x in members))<2:continue
        if not want_year and component and all(period(m.answer) for m in members):continue
        if not fit(tokens(lab)) and not fit(tokens(sec)):continue
        cue=tokens(lab+" "+sec)
        push("row "+str(r)+" | "+lab+" | "+sec,"row",cue,members,.35 if want_year else 0,True)
        # Under repeated periods, each metric subheader identifies an alternate range.
        partitions=defaultdict(list)
        for m in members:
            non_year=" ".join(w for w in clean(hdr[m.col]).split() if not years(w))
            if non_year:partitions[non_year].append(m)
        for label,part in partitions.items():
            if 1<len(part)<len(members):
                push("row "+str(r)+" / "+label,"row",cue|tokens(label),part)

    # Vertical comparisons: all named rows, component rows, explicit section scopes,
    # and rows that repeat the same metric under different year section headings.
    for c,header in enumerate(hdr[1:],1):
        yr=period(header)
        if not want_year and qyears and yr and not set(years(yr))&qyears:continue
        records=[]
        for r,lab,sec in data:
            date=period(sec) or period(lab)
            ans=date if want_year else lab
            if not ans or (want_year and len(qyears)>=2 and not set(years(date))&qyears):continue
            m=member(r,c,ans,lab,sec)
            if m:records.append((m,lab,sec))
        if not records:continue
        def add_vertical(name,context,subset,bias=0,flat_eligible=False):
            push(name+" | col "+str(c),"col",tokens(header+" "+context),[x[0] for x in subset],bias,flat_eligible)
        if want_year:
            by_metric=defaultdict(list)
            for item in records:by_metric[clean(item[1])].append(item)
            for metric,sub in by_metric.items():
                if len({m.answer for m,_,_ in sub})>=2 and fit(tokens(metric))>0:
                    add_vertical("same row under period sections",metric,sub,.3,True)
            if all(period(lab) for _,lab,_ in records):
                add_vertical("period rows","",records,.3,True)
            continue
        if not fit(tokens(header)) and len(hdr)>2 and not qyears:continue
        preferred=.45 if component else 0.
        if qyears and not yr and not(set(years(header))&qyears):
            if any(period(s) for s in hdr[1:]):continue
        add_vertical("whole column","",records,preferred,True)
        detail_rows=[x for x in records if not total(x[1])]
        if len(detail_rows)!=len(records):
            add_vertical("components only","",detail_rows,preferred+(.75 if component else 0))
        sections=defaultdict(list)
        for item in records:
            if item[2]:sections[item[2]].append(item)
        for sec,part in sections.items():
            if len(part)>=len(records):continue
            eligible=[x for x in part if not component or not total(x[1])]
            add_vertical("section "+sec,sec,eligible,preferred)
    def choose(cands):
        if not cands:return None
        return max(cands,key=lambda x:(round(x.score,6),len(x.members)))
    def format_range(x):
        return {"title":x.title,"score":round(x.score,4),"answer":x.answer,"members":[[m.row,m.col,m.answer,m.raw] for m in x.members],"winners":[[m.row,m.col] for m in x.winners]}
    base=choose(pool);simple=choose(flat)
    if base is None:return {"base":None,"contrast":None,"flat":None,"trace":{"reason":"no eligible range","ranges":[]}}
    selected=base;reason="same range";ranked=[]
    def coords(range_):return {(m.row,m.col) for m in range_.members}
    # Compare the baseline membership to each alternative. Only distinctions
    # between included and excluded members contribute extra lexical evidence.
    for alt in pool:
        if alt is base or alt.answer==base.answer or alt.axis!=base.axis:continue
        a=coords(alt);b=coords(base)
        inside=[m for m in alt.members if (m.row,m.col) not in b]
        outside=[m for m in base.members if (m.row,m.col) not in a]
        def common(members):
            return set.intersection(*(set(m.attributes) for m in members)) if members else set()
        # For nested ranges compare retained rows against those the scope excludes.
        in_attr=common(inside or alt.members)
        out_attr=common(outside or base.members)
        plus=(in_attr-out_attr)&qt
        minus=(out_attr-in_attr)&qt
        delta=sum(weight(w) for w in plus)-sum(weight(w) for w in minus)
        if abs(delta)>0:
            ranked.append((alt.score-base.score + .80*delta,alt,sorted(plus),sorted(minus)))
    if ranked:
        margin,pick,pro,con=max(ranked,key=lambda x:x[0])
        if margin>.55 and pro and pick.answer is not None:selected=pick;reason="distinctive member support"
    proposals=sorted(pool,key=lambda x:-x.score)
    return {"flat":simple.answer if simple else None,"base":base.answer,"contrast":selected.answer,
            "trace":{"reason":reason,"op":op[0],"base_scope":format_range(base),"contrast_scope":format_range(selected),
                     "ranges":[format_range(x) for x in proposals],
                     "contrast_checks":[{"range":a.title,"margin":round(v,4),"for":pro,"against":con} for v,a,pro,con in ranked]}}
