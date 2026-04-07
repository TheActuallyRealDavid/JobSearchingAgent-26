#!/usr/bin/env python3
"""Job Search Agent — lightweight backend using Python stdlib."""

import json
import os
import uuid
import mimetypes
import urllib.parse
import urllib.request
import ssl
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_DIR = os.path.join(BASE_DIR, "resumes")
DATA_FILE = os.path.join(BASE_DIR, "resume_data.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
BLOCKED_FILE = os.path.join(BASE_DIR, "blocked_jobs.json")

# Try importing pdfplumber for text extraction
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# ── Data helpers ──

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"resumes": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_default_resume(data):
    for r in data["resumes"]:
        if r.get("is_default"):
            return r
    return data["resumes"][0] if data["resumes"] else None

def get_all_resume_texts(data):
    """Return list of (filename, extracted_text) for all resumes."""
    return [(r["filename"], r.get("extracted_text", "")) for r in data["resumes"]]

def extract_pdf_text(filepath):
    if not HAS_PDFPLUMBER:
        return ""
    try:
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        return text.strip()
    except Exception:
        return ""

# ── Settings helpers ──

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

# ── Blocked jobs helpers ──

def load_blocked():
    if os.path.exists(BLOCKED_FILE):
        with open(BLOCKED_FILE, "r") as f:
            return json.load(f)
    return {"blocked": []}

def save_blocked(data):
    with open(BLOCKED_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── JSearch API ──

REACH_COMPANIES = {
    "google", "meta", "apple", "microsoft", "openai", "netflix",
    "stripe", "airbnb", "uber", "lyft", "snap", "pinterest",
    "palantir", "databricks", "coinbase", "jane street", "citadel",
    "two sigma", "de shaw", "hudson river trading",
}

def search_jobs_jsearch(query="software engineer intern fall 2026", num_results=20):
    """Search for jobs using JSearch API on RapidAPI."""
    settings = load_settings()
    api_key = settings.get("rapidapi_key", "")
    if not api_key:
        return None  # Signal to use sample data

    # JSearch returns ~10 jobs per page; fetch enough pages for num_results
    pages_needed = max(1, min(10, (num_results + 9) // 10))
    params = urllib.parse.urlencode({
        "query": query,
        "page": "1",
        "num_pages": str(pages_needed),
        "country": "us",
        "date_posted": "month",
    })

    url = f"https://jsearch.p.rapidapi.com/search?{params}"
    req = urllib.request.Request(url)
    req.add_header("x-rapidapi-key", api_key)
    req.add_header("x-rapidapi-host", "jsearch.p.rapidapi.com")

    try:
        ctx = ssl.create_default_context()
        # Fallback for macOS missing certs
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except ImportError:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = json.loads(resp.read().decode())

        jobs = []
        for item in raw.get("data", [])[:num_results]:
            employer = item.get("employer_name", "Unknown")
            is_remote = item.get("job_is_remote", False)

            # Determine format
            if is_remote:
                work_format = "Remote"
            else:
                work_format = "On-site"

            # Check for hybrid signals in title or description
            title = item.get("job_title", "")
            desc = item.get("job_description", "") or ""
            if "hybrid" in title.lower() or "hybrid" in desc[:500].lower():
                work_format = "Hybrid"

            # Pay range
            min_sal = item.get("job_min_salary")
            max_sal = item.get("job_max_salary")
            sal_period = item.get("job_salary_period", "")

            pay_range = None
            if min_sal and max_sal:
                if sal_period and sal_period.upper() == "HOUR":
                    pay_range = f"${int(min_sal)}-{int(max_sal)}/hr"
                elif sal_period and sal_period.upper() == "YEAR":
                    # Convert annual to rough hourly (assuming 40hr/week internship)
                    hr_min = int(min_sal) // 2080
                    hr_max = int(max_sal) // 2080
                    pay_range = f"~${hr_min}-{hr_max}/hr"
                else:
                    pay_range = f"${int(min_sal)}-{int(max_sal)}"
            elif min_sal:
                if sal_period and sal_period.upper() == "HOUR":
                    pay_range = f"${int(min_sal)}/hr+"
                else:
                    pay_range = f"${int(min_sal)}+"

            # Location
            city = item.get("job_city", "")
            state = item.get("job_state", "")
            location = f"{city}, {state}" if city and state else city or state or "USA"

            # Reach detection
            is_reach = employer.lower().strip() in REACH_COMPANIES

            # Truncate description for cover letter use
            short_desc = desc[:800] if desc else title

            jobs.append({
                "company": employer,
                "position": title,
                "location": location,
                "format": work_format,
                "pay_range": pay_range,
                "is_reach": is_reach,
                "description": short_desc,
                "apply_link": item.get("job_apply_link", ""),
            })

        return jobs

    except Exception as e:
        print(f"JSearch API error: {e}")
        return None

# ── Multipart parser ──

def parse_multipart(body, content_type):
    """Parse multipart/form-data and return dict of {fieldname: (filename, data)}."""
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip('"')
            break
    if not boundary:
        return {}

    boundary_bytes = ("--" + boundary).encode()
    end_boundary = (boundary_bytes + b"--")
    parts = body.split(boundary_bytes)
    result = {}

    for part in parts:
        if not part or part.strip() == b"" or part.strip() == b"--":
            continue
        if b"\r\n\r\n" in part:
            header_section, file_data = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_section, file_data = part.split(b"\n\n", 1)
        else:
            continue

        # Strip trailing \r\n
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]
        elif file_data.endswith(b"\n"):
            file_data = file_data[:-1]
        # Strip trailing --
        if file_data.endswith(b"--"):
            file_data = file_data[:-2]
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]

        headers_str = header_section.decode("utf-8", errors="replace")
        name = None
        filename = None
        for line in headers_str.split("\n"):
            line = line.strip()
            if line.lower().startswith("content-disposition:"):
                for param in line.split(";"):
                    param = param.strip()
                    if param.startswith("name="):
                        name = param.split("=", 1)[1].strip('"')
                    elif param.startswith("filename="):
                        filename = param.split("=", 1)[1].strip('"')

        if name:
            result[name] = (filename, file_data)

    return result

# ── Job data ──

SAMPLE_JOBS = [
    {
        "company": "Amazon",
        "position": "Robotics SDE Intern/Co-op 2026",
        "location": "North Reading, MA",
        "format": "On-site",
        "pay_range": "$47-52/hr",
        "is_reach": False,
        "description": "Design, develop, and test software for fulfillment center robotics, material handling, computer vision, and cloud services. Work with Python, Java, and C++ on production systems at scale.",
        "apply_link": "https://www.amazon.jobs/en/teams/internships-for-students"
    },
    {
        "company": "OpenAI",
        "position": "Software Engineer Intern/Co-op, Applied (Fall 2026)",
        "location": "San Francisco, CA",
        "format": "On-site",
        "pay_range": None,
        "is_reach": True,
        "description": "15-week internship building applied AI products. Requires proficiency in JavaScript, React, Python, and experience with relational databases (Postgres/MySQL). Work on user-facing AI applications.",
        "apply_link": "https://openai.com/careers"
    },
    {
        "company": "Meta",
        "position": "Software Engineer Intern/Co-op",
        "location": "Menlo Park, CA",
        "format": "On-site",
        "pay_range": "$50-55/hr",
        "is_reach": True,
        "description": "Contribute to full-stack development on Meta's core products. Strong knowledge of data structures, algorithms, and systems design. Experience with C++, Java, or Python required.",
        "apply_link": "https://www.metacareers.com/careerprograms/students"
    },
    {
        "company": "Microsoft",
        "position": "Software Engineering Intern",
        "location": "Redmond, WA",
        "format": "Hybrid",
        "pay_range": "$47-52/hr",
        "is_reach": True,
        "description": "Work on cutting-edge technology projects with real business impact. Full-stack or systems-level work across Azure, Office, Windows, or other teams. Proficiency in C++, C#, Java, or Python.",
        "apply_link": "https://careers.microsoft.com/v2/global/en/universityinternship"
    },
    {
        "company": "Apple",
        "position": "Software Engineering Intern",
        "location": "Cupertino, CA",
        "format": "On-site",
        "pay_range": "$45-55/hr",
        "is_reach": True,
        "description": "Join a software development team building the next generation of Apple products and services. Experience with Swift, Objective-C, C++, or Python. Strong fundamentals in algorithms and data structures.",
        "apply_link": "https://jobs.apple.com/en-us/search?team=internships-STDNT-INTRN"
    },
    {
        "company": "NVIDIA",
        "position": "Developer Technology Intern (Fall 2026)",
        "location": "Santa Clara, CA",
        "format": "On-site",
        "pay_range": "$40-55/hr",
        "is_reach": False,
        "description": "Work on GPU-accelerated computing and high-performance software. Strong C/C++ programming skills required. Experience with systems programming, parallel computing, or graphics is a plus.",
        "apply_link": "https://www.nvidia.com/en-us/about-nvidia/careers/university-recruiting/"
    },
    {
        "company": "Qualcomm",
        "position": "Software Engineering Intern",
        "location": "San Diego, CA",
        "format": "On-site",
        "pay_range": "$30-45/hr",
        "is_reach": False,
        "description": "Develop embedded and application-level software for mobile and IoT platforms. Requires proficiency in C/C++, Python, or Java. Graduation between Nov 2026 and Jun 2027.",
        "apply_link": "https://careers.qualcomm.com/careers/internships"
    },
    {
        "company": "JPMorgan Chase",
        "position": "Software Engineer Intern",
        "location": "New York, NY",
        "format": "Hybrid",
        "pay_range": "$38-45/hr",
        "is_reach": False,
        "description": "Build and optimize digital applications and systems supporting millions of customers. Work with Java, Python, React, Node.js, and cloud platforms in an agile team environment.",
        "apply_link": "https://careers.jpmorgan.com/us/en/students/programs/software-engineer-summer"
    },
    {
        "company": "Boeing",
        "position": "Software Engineering Intern",
        "location": "Seattle, WA",
        "format": "On-site",
        "pay_range": "$25-38/hr",
        "is_reach": False,
        "description": "12-week program developing software for aerospace systems. Experience with C/C++, Java, or Python. Work on real projects with business impact in avionics, simulation, or data systems.",
        "apply_link": "https://jobs.boeing.com/entry-level"
    },
    {
        "company": "Lockheed Martin",
        "position": "Software Engineering Intern",
        "location": "Fort Worth, TX",
        "format": "On-site",
        "pay_range": "$22-35/hr",
        "is_reach": False,
        "description": "Develop software for defense and aerospace systems. Strong C/C++ and systems programming skills valued. Must be eligible for security clearance (US citizenship required).",
        "apply_link": "https://www.lockheedmartinjobs.com/college-students"
    },
    {
        "company": "Google",
        "position": "Software Engineering Intern, Fall 2026",
        "location": "Mountain View, CA",
        "format": "Hybrid",
        "pay_range": "$50-58/hr",
        "is_reach": True,
        "description": "Work on core products like Search, Maps, Chrome, or Cloud. Strong CS fundamentals, algorithms, and data structures required. Experience with C++, Java, Python, or Go preferred.",
        "apply_link": "https://www.google.com/about/careers/applications/students/"
    },
    {
        "company": "IBM",
        "position": "Software Developer Intern",
        "location": "Research Triangle Park, NC",
        "format": "Hybrid",
        "pay_range": "$30-42/hr",
        "is_reach": False,
        "description": "Join a team building cloud and AI solutions. Work with Java, Python, Node.js, and Kubernetes. Collaborate with experienced engineers on enterprise software.",
        "apply_link": "https://www.ibm.com/careers/search?field_of_work=Internship"
    },
    {
        "company": "Cisco",
        "position": "Software Engineer Intern (Fall 2026)",
        "location": "San Jose, CA",
        "format": "Hybrid",
        "pay_range": "$30-45/hr",
        "is_reach": False,
        "description": "Develop networking and security software. Experience with Python, C/C++, or Go. Work on products used by enterprises worldwide.",
        "apply_link": "https://jobs.cisco.com/jobs/SearchJobs/intern"
    },
    {
        "company": "Intel",
        "position": "Software Engineering Intern",
        "location": "Hillsboro, OR",
        "format": "On-site",
        "pay_range": "$28-42/hr",
        "is_reach": False,
        "description": "Contribute to software for next-gen processors and platforms. Strong C/C++ skills required. Interest in systems programming, compilers, or performance optimization.",
        "apply_link": "https://jobs.intel.com/en/search-jobs?k=intern"
    },
    {
        "company": "Salesforce",
        "position": "Software Engineer Intern",
        "location": "San Francisco, CA",
        "format": "Hybrid",
        "pay_range": "$45-55/hr",
        "is_reach": False,
        "description": "Build cloud-based CRM applications at scale. Full-stack development with Java, JavaScript/React, and relational databases. Agile team environment.",
        "apply_link": "https://careers.salesforce.com/en/jobs/?team=Intern"
    },
    {
        "company": "Oracle",
        "position": "Software Engineer Intern",
        "location": "Austin, TX",
        "format": "On-site",
        "pay_range": "$35-48/hr",
        "is_reach": False,
        "description": "Work on Oracle Cloud Infrastructure or database products. Java, Python, or C++ experience required. Build high-performance distributed systems.",
        "apply_link": "https://www.oracle.com/careers/students-grads/"
    },
    {
        "company": "Raytheon",
        "position": "Software Engineering Intern (Fall 2026)",
        "location": "Tewksbury, MA",
        "format": "On-site",
        "pay_range": "$25-38/hr",
        "is_reach": False,
        "description": "Develop software for defense systems including radar, missiles, and cybersecurity. C/C++, Java, or Python. US citizenship required for security clearance.",
        "apply_link": "https://careers.rtx.com/global/en/raytheon-early-careers"
    },
    {
        "company": "Tesla",
        "position": "Software Engineering Intern, Vehicle Software",
        "location": "Palo Alto, CA",
        "format": "On-site",
        "pay_range": "$35-50/hr",
        "is_reach": False,
        "description": "Develop embedded and application software for Tesla vehicles. C/C++, Python experience. Work on autopilot, infotainment, or factory systems.",
        "apply_link": "https://www.tesla.com/careers/internships"
    },
    {
        "company": "Palantir",
        "position": "Software Engineer Intern",
        "location": "New York, NY",
        "format": "On-site",
        "pay_range": "$50-60/hr",
        "is_reach": True,
        "description": "Build software that empowers organizations to use data effectively. Strong algorithms and systems design skills. Java, C++, or TypeScript experience.",
        "apply_link": "https://www.palantir.com/careers/students/"
    },
    {
        "company": "General Motors",
        "position": "Software Developer Intern",
        "location": "Warren, MI",
        "format": "Hybrid",
        "pay_range": "$28-40/hr",
        "is_reach": False,
        "description": "Work on next-gen vehicle software and connected services. Python, Java, or C++ experience. Contribute to EV and autonomous vehicle platforms.",
        "apply_link": "https://search-careers.gm.com/en/jobs/?search=intern+software"
    },
]

# ── Reach ratio enforcement ──

REACH_SAMPLE_JOBS = [j for j in SAMPLE_JOBS if j.get("is_reach")]

import random

def ensure_reach_ratio(jobs):
    """Ensure at least 1/5 of results are reach roles."""
    total = len(jobs)
    if total == 0:
        return jobs

    reach_needed = max(1, total // 5)
    reach_count = sum(1 for j in jobs if j.get("is_reach"))

    if reach_count >= reach_needed:
        return jobs

    # Need to inject reach roles
    to_add = reach_needed - reach_count
    # Pick from reach sample jobs, avoid duplicating companies already present
    existing_companies = {j["company"].lower() for j in jobs}
    candidates = [j for j in REACH_SAMPLE_JOBS if j["company"].lower() not in existing_companies]

    if not candidates:
        candidates = REACH_SAMPLE_JOBS  # fallback: allow duplicates

    random.shuffle(candidates)
    injected = candidates[:to_add]

    # Insert reach jobs at evenly spaced positions
    result = list(jobs)
    for i, rj in enumerate(injected):
        pos = min(len(result), (i + 1) * (len(result) // (to_add + 1)))
        result.insert(pos, rj)

    return result

# ── Cover letter / Resume tips generation ──

def generate_cover_letter_content(job, data):
    default = get_default_resume(data)
    resume_text = default.get("extracted_text", "") if default else ""
    all_texts = get_all_resume_texts(data)

    if not resume_text:
        return "<p><em>No default resume set or resume text could not be extracted. Please upload a resume and set it as default in the Resume Manager.</em></p>"

    # Parse resume for key info
    name = extract_field(resume_text, "name")
    skills = extract_skills(resume_text)
    projects = extract_projects(resume_text)

    # Check other resume versions for relevant missing content
    memory_flags = []
    if len(all_texts) > 1 and default:
        default_text = default.get("extracted_text", "").lower()
        job_desc_lower = job.get("description", "").lower()
        for fname, txt in all_texts:
            if fname == default.get("filename"):
                continue
            if not txt:
                continue
            # Look for skills in old resumes not in current default
            old_skills = extract_skills(txt)
            for s in old_skills:
                if s.lower() not in default_text and s.lower() in job_desc_lower:
                    memory_flags.append(f'Your previous resume (<strong>{fname}</strong>) listed <strong>{s}</strong>. Consider re-adding it — it\'s relevant to this role.')

    company = job.get("company", "the company")
    position = job.get("position", "the position")
    location = job.get("location", "")
    description = job.get("description", "")

    # Build cover letter
    letter = f"""<h4>Cover Letter — {position} at {company}</h4>

<p>Dear Hiring Manager,</p>

<p>I am writing to express my interest in the <strong>{position}</strong> position at <strong>{company}</strong>{f' in {location}' if location else ''}. I am currently pursuing a B.S. in Computer Science at Drexel University with an anticipated graduation in Spring 2027, and I am eager to contribute my technical skills and project experience to your team.</p>

<p>"""

    # Match skills to job description
    matched_skills = []
    desc_lower = description.lower()
    for skill in skills:
        if skill.lower() in desc_lower:
            matched_skills.append(skill)

    if matched_skills:
        letter += f"My technical toolkit includes <strong>{', '.join(matched_skills)}</strong>, which directly align with the requirements of this role. "

    # Highlight relevant projects
    if "react" in desc_lower or "full-stack" in desc_lower or "javascript" in desc_lower:
        letter += "Through my work as Design Lead at Hack4Impact Drexel, I spearheaded the full-stack modernization of a waste tracking system using React and Node.js, architecting a Supabase backend with optimized SQL queries that eliminated manual input errors and saved 10 hours of administrative overhead per month. "
    if "python" in desc_lower or "ai" in desc_lower or "ml" in desc_lower:
        letter += "I am also currently building Bit, an AI desktop assistant powered by a locally hosted open-source LLM, where I developed an OCR pipeline for screen data ingestion and synchronized real-time inference with custom animated assets. "
    if "c++" in desc_lower or "c/" in desc_lower or "systems" in desc_lower:
        letter += "My systems programming experience includes constructing a custom Unix shell in C, utilizing low-level system calls for process creation, execution, and memory management, and optimizing execution flow for concurrent processes and I/O redirection. "
    if "java" in desc_lower:
        letter += "I have hands-on experience building enterprise-grade software in Java, including a banking system utilizing OOP principles to manage secure transactions, account states, and user data persistence with rigorous data validation protocols. "

    letter += """</p>

<p>Beyond my technical abilities, I bring strong leadership and collaboration skills. As Event Coordinator for Drexel Hack4Impact, I directed logistics for a Technical Project Showcase serving 200+ students, secured $2,500+ in corporate sponsorship, and grew membership by 600%. I thrive in team environments and am experienced in Agile workflows, sprint planning, and cross-functional communication.</p>

<p>I am excited about the opportunity to bring my passion for building impactful software to <strong>""" + company + """</strong>. I would welcome the chance to discuss how my experience and skills can contribute to your team. Thank you for considering my application.</p>

<p>Sincerely,<br>""" + name + """</p>"""

    # Add memory flags if any
    if memory_flags:
        for flag in memory_flags:
            letter += f'\n<div class="memory-flag">{flag}</div>'

    # Style principles applied
    letter += """
<div class="memory-flag"><strong>Writing principles applied to this letter:</strong>
<ul style="margin:8px 0 0 18px;">
<li>Action verbs (built, led, architected, secured) — never "responsible for"</li>
<li>Quantified impact ($2,500+ sponsorship, 600% growth, 10 hrs/month saved, 200+ students)</li>
<li>Specific collaboration callouts instead of vague "worked with team"</li>
<li>Keywords mirrored from the job description above</li>
<li>STAR-style framing on every project mentioned</li>
</ul></div>"""

    return letter


def audit_resume_red_flags(resume_text, job_desc):
    """Scan resume against the 9 red-flag rules."""
    lower = resume_text.lower()
    flags = []

    # 1. "Responsible for" / passive language
    weak_phrases = ["responsible for", "duties included", "tasked with", "in charge of", "helped with"]
    found_weak = [p for p in weak_phrases if p in lower]
    if found_weak:
        flags.append(("Weak phrasing", f"Found <code>{', '.join(found_weak)}</code>. Replace with action verbs: <strong>Built, Led, Reduced, Increased, Architected, Shipped, Optimized.</strong>"))

    # 2. No numbers — count digits
    digit_count = sum(c.isdigit() for c in resume_text)
    word_count = max(len(resume_text.split()), 1)
    digit_ratio = digit_count / word_count
    if digit_ratio < 0.05:
        flags.append(("Not enough numbers", "Your resume is light on metrics. Quantify everything you can: <strong>40% faster, 2M users, $10k saved, 5-person team, 200+ users.</strong>"))

    # 3. Vague team language
    if "worked with" in lower or "team player" in lower:
        flags.append(("Vague collaboration", "Replace <code>worked with team</code> with specifics: <strong>Led 5-person team, Collaborated with PM and 3 engineers, Mentored 2 junior devs.</strong>"))

    # 4. Skills randomly listed — check if any job keywords are missing
    # (handled by skill gap analysis below)

    # 5. Objective statement
    if "objective:" in lower or "career objective" in lower or "objective statement" in lower:
        flags.append(("Objective statement", "Delete the objective statement. Recruiters skip it. Use that space for an additional project or impact bullet."))

    # 6. Generic descriptions / no STAR
    generic_tells = ["various", "many", "different projects", "etc."]
    found_generic = [g for g in generic_tells if g in lower]
    if found_generic:
        flags.append(("Generic descriptions", f"Found <code>{', '.join(found_generic)}</code>. Use STAR format: <strong>Situation → Task → Action → Result.</strong>"))

    # 7. Microsoft Office
    if "microsoft office" in lower or "ms office" in lower or "proficient in word" in lower:
        flags.append(("Filler skills", "Remove <code>Microsoft Office / MS Word</code>. List only technical skills that matter for this role."))

    # 8. Length — rough page estimate
    if word_count > 700:
        flags.append(("Possibly 2+ pages", f"Your resume has ~{word_count} words. Aim for ≤ 600 words / 1 page unless you have 10+ years of experience."))

    # 9. Fancy formatting — check for unusual characters
    fancy_chars = sum(1 for c in resume_text if ord(c) > 8000)
    if fancy_chars > 30:
        flags.append(("Fancy formatting", "Detected non-standard characters or symbols. Use a simple ATS-friendly layout — single column, standard fonts, no icons or graphics."))

    return flags


def generate_resume_tips_content(job, data):
    default = get_default_resume(data)
    resume_text = default.get("extracted_text", "") if default else ""
    all_texts = get_all_resume_texts(data)

    if not resume_text:
        return "<p><em>No default resume set or resume text could not be extracted. Please upload a resume in the Resume Manager.</em></p>"

    company = job.get("company", "the company")
    position = job.get("position", "the position")
    description = job.get("description", "")
    desc_lower = description.lower()
    resume_lower = resume_text.lower()

    tips = f"<h4>Resume Tips for {position} at {company}</h4>"

    # Red Flags Audit — scan resume for the 9 killers
    red_flags = audit_resume_red_flags(resume_text, description)
    if red_flags:
        tips += "<h4>Red Flags Found in Your Resume</h4><ul>"
        for label, msg in red_flags:
            tips += f"<li><strong>{label}:</strong> {msg}</li>"
        tips += "</ul>"
    else:
        tips += '<div class="memory-flag"><strong>Red Flags Audit:</strong> Your resume passed all 9 killer checks (action verbs, quantified impact, specific collaboration, no objective, no filler skills, ATS-friendly).</div>'

    tips += "<h4>Tailoring for This Role</h4><ul>"

    # Check for skill gaps
    job_keywords = {
        "Python": "python", "Java": "java", "C++": "c++", "C": " c ",
        "JavaScript": "javascript", "React": "react", "Node.js": "node.js",
        "SQL": "sql", "Swift": "swift", "Go": "golang",
        "Kubernetes": "kubernetes", "Docker": "docker", "AWS": "aws",
        "Azure": "azure", "GCP": "gcp", "machine learning": "machine learning",
        "data structures": "data structures", "algorithms": "algorithm",
        "systems design": "systems design", "REST API": "rest api",
        "agile": "agile", "git": "git",
    }

    present_and_relevant = []
    missing_but_needed = []

    for display, keyword in job_keywords.items():
        in_job = keyword in desc_lower
        in_resume = keyword in resume_lower
        if in_job and in_resume:
            present_and_relevant.append(display)
        elif in_job and not in_resume:
            missing_but_needed.append(display)

    if present_and_relevant:
        tips += f"<li><strong>Skills already matching:</strong> {', '.join(present_and_relevant)}. Make sure these are prominently featured in your Skills section.</li>"

    if missing_but_needed:
        tips += f"<li><strong>Consider adding if applicable:</strong> {', '.join(missing_but_needed)}. The job description mentions these — if you have experience with them, add them to your resume.</li>"

    # Project relevance
    if "full-stack" in desc_lower or "react" in desc_lower:
        tips += "<li><strong>Highlight DCCI project:</strong> Your Hack4Impact work with React, Node.js, and Supabase is a strong match. Consider moving it higher or expanding the bullet points to emphasize full-stack scope.</li>"

    if "ai" in desc_lower or "ml" in desc_lower or "machine learning" in desc_lower:
        tips += "<li><strong>Expand on Bit (AI Assistant):</strong> Emphasize the LLM integration, OCR pipeline, and any ML-adjacent work. Quantify results where possible.</li>"

    if "c++" in desc_lower or "systems" in desc_lower:
        tips += "<li><strong>Feature Unix Shell project:</strong> Your custom shell in C demonstrates strong systems programming fundamentals. Consider adding metrics (e.g., number of built-in commands, test coverage).</li>"

    if "java" in desc_lower:
        tips += "<li><strong>Emphasize Banking System project:</strong> Your Java enterprise project with OOP, secure transactions, and data validation is directly relevant. Consider quantifying (e.g., number of transaction types, data integrity tests).</li>"

    # General tips specific to the role
    if job.get("is_reach"):
        tips += "<li><strong>This is a reach role</strong> — tailor your resume specifically for this company. Research their tech stack and mirror their terminology. A strong cover letter is especially important here.</li>"

    if not job.get("pay_range"):
        tips += "<li><strong>Pay not disclosed:</strong> Research typical intern compensation at this company on Levels.fyi or Glassdoor before interviews.</li>"

    # Cross-reference old resumes
    if len(all_texts) > 1 and default:
        default_text_lower = default.get("extracted_text", "").lower()
        for fname, txt in all_texts:
            if fname == default.get("filename"):
                continue
            if not txt:
                continue
            old_skills = extract_skills(txt)
            for s in old_skills:
                if s.lower() not in default_text_lower and s.lower() in desc_lower:
                    tips += f'<li class="memory-flag"><strong>From previous resume ({fname}):</strong> You previously listed <strong>{s}</strong>. Consider re-adding it for this application.</li>'

    tips += "</ul>"

    # Check if tips are mostly generic
    if not missing_but_needed and not job.get("is_reach"):
        tips += "<p><strong>Overall:</strong> Your resume is already well-aligned with this role. Focus on quantifying impact in your bullet points and tailoring your summary to the specific team/product.</p>"

    return tips


def extract_field(text, field):
    """Extract basic fields from resume text."""
    if field == "name":
        lines = text.strip().split("\n")
        if lines:
            return lines[0].strip()
    return ""


def extract_skills(text):
    """Extract skills from resume text."""
    known_skills = [
        "JavaScript", "Python", "HTML/CSS", "C/C++", "Bash", "Java",
        "Node.js", "React.js", "React", "SQL", "FastAPI", "Git",
        "Postman", "Agile", "Figma", "Supabase", "Firebase",
        "Django", "React Native", "C", "TypeScript", "Swift",
        "Docker", "Kubernetes", "AWS", "REST API",
    ]
    found = []
    text_lower = text.lower()
    for s in known_skills:
        if s.lower() in text_lower:
            found.append(s)
    return found


def extract_projects(text):
    """Extract project names from resume text."""
    projects = []
    keywords = ["DCCI", "PawNav", "Bit", "Unix Shell", "Banking Software"]
    for kw in keywords:
        if kw.lower() in text.lower():
            projects.append(kw)
    return projects


# ── HTTP Handler ──

class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        # Root — serve index.html directly
        if path == "/" or path == "":
            path = "/static/index.html"

        # Static files
        if path.startswith("/static/"):
            self.serve_static(path)
            return

        # Get settings (masked key)
        if path == "/api/settings":
            settings = load_settings()
            key = settings.get("rapidapi_key", "")
            masked = ""
            if key:
                masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
            self.json_response({"has_key": bool(key), "masked_key": masked})
            return

        # Get blocked jobs
        if path == "/api/blocked-jobs":
            data = load_blocked()
            self.json_response(data)
            return

        # List resumes
        if path == "/api/resumes":
            data = load_data()
            self.json_response(data)
            return

        # View resume PDF
        if path.startswith("/api/resumes/") and path.endswith("/view"):
            resume_id = path.split("/")[3]
            data = load_data()
            for r in data["resumes"]:
                if r["id"] == resume_id:
                    filepath = os.path.join(BASE_DIR, r["file_path"])
                    if os.path.exists(filepath):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/pdf")
                        self.send_header("Content-Disposition", f'inline; filename="{r["filename"]}"')
                        self.end_headers()
                        with open(filepath, "rb") as f:
                            self.wfile.write(f.read())
                        return
            self.send_error(404, "Resume not found")
            return

        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # Upload resume
        if path == "/api/resumes/upload":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.json_response({"error": "Expected multipart/form-data"}, 400)
                return

            parts = parse_multipart(body, content_type)
            if "file" not in parts:
                self.json_response({"error": "No file provided"}, 400)
                return

            filename, file_data = parts["file"]
            if not filename or not filename.lower().endswith(".pdf"):
                self.json_response({"error": "Only PDF files are accepted"}, 400)
                return

            # Save file
            file_id = str(uuid.uuid4())
            save_path = os.path.join(RESUMES_DIR, f"{file_id}.pdf")
            with open(save_path, "wb") as f:
                f.write(file_data)

            # Extract text
            extracted = extract_pdf_text(save_path)

            # Save metadata
            data = load_data()
            is_first = len(data["resumes"]) == 0
            entry = {
                "id": file_id,
                "filename": filename,
                "upload_date": datetime.now().isoformat(),
                "is_default": is_first,
                "file_path": f"resumes/{file_id}.pdf",
                "extracted_text": extracted,
            }
            data["resumes"].append(entry)
            save_data(data)

            response = {"success": True, "resume": entry}
            if not HAS_PDFPLUMBER:
                response["warning"] = "pdfplumber not installed — text extraction unavailable"
            self.json_response(response)
            return

        # Set default resume
        if path == "/api/resumes/default":
            payload = json.loads(body)
            resume_id = payload.get("id")
            data = load_data()
            for r in data["resumes"]:
                r["is_default"] = (r["id"] == resume_id)
            save_data(data)
            self.json_response({"success": True})
            return

        # Save settings
        if path == "/api/settings":
            payload = json.loads(body)
            settings = load_settings()
            if "rapidapi_key" in payload:
                settings["rapidapi_key"] = payload["rapidapi_key"].strip()
            save_settings(settings)
            self.json_response({"success": True})
            return

        # Block a job
        if path == "/api/blocked-jobs":
            payload = json.loads(body)
            data = load_blocked()
            # Avoid duplicates
            existing_keys = {b["key"] for b in data["blocked"]}
            if payload.get("key") not in existing_keys:
                data["blocked"].append({
                    "key": payload["key"],
                    "company": payload.get("company", ""),
                    "position": payload.get("position", ""),
                    "reason": payload.get("reason", ""),
                    "date": datetime.now().isoformat(),
                })
                save_blocked(data)
            self.json_response({"success": True})
            return

        # Search jobs
        if path == "/api/jobs/search":
            payload = json.loads(body) if body else {}
            query = payload.get("query", "software engineer intern fall 2026")
            count = max(1, min(int(payload.get("count", 10)), 100))

            # Try live search first
            live_jobs = search_jobs_jsearch(query, num_results=count)
            if live_jobs is not None:
                jobs = ensure_reach_ratio(live_jobs)
                self.json_response({"jobs": jobs, "source": "live"})
            else:
                self.json_response({"jobs": SAMPLE_JOBS[:count], "source": "sample"})
            return

        # Generate cover letter
        if path == "/api/generate/cover-letter":
            payload = json.loads(body)
            job = payload.get("job", {})
            data = load_data()
            content = generate_cover_letter_content(job, data)
            self.json_response({"content": content})
            return

        # Generate resume tips
        if path == "/api/generate/resume-tips":
            payload = json.loads(body)
            job = payload.get("job", {})
            data = load_data()
            content = generate_resume_tips_content(job, data)
            self.json_response({"content": content})
            return

        self.send_error(404)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path

        # Delete resume: /api/resumes/<id>
        if path.startswith("/api/resumes/"):
            resume_id = path.split("/")[3]
            data = load_data()
            resume = None
            for r in data["resumes"]:
                if r["id"] == resume_id:
                    resume = r
                    break
            if not resume:
                self.send_error(404, "Resume not found")
                return

            # Remove file
            filepath = os.path.join(BASE_DIR, resume["file_path"])
            if os.path.exists(filepath):
                os.remove(filepath)

            was_default = resume.get("is_default", False)
            data["resumes"] = [r for r in data["resumes"] if r["id"] != resume_id]

            # If deleted resume was default, set first remaining as default
            if was_default and data["resumes"]:
                data["resumes"][0]["is_default"] = True

            save_data(data)
            self.json_response({"success": True})
            return

        self.send_error(404)

    def serve_static(self, path):
        rel = path[len("/static/"):]
        filepath = os.path.join(BASE_DIR, "static", rel)
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(filepath)
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quieter logging
        pass


if __name__ == "__main__":
    os.makedirs(RESUMES_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        save_data({"resumes": []})

    print(f"Job Search Agent running at http://localhost:{PORT}")
    print(f"PDF text extraction: {'enabled' if HAS_PDFPLUMBER else 'disabled (pip3 install pdfplumber)'}")
    print("Press Ctrl+C to stop.")

    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
