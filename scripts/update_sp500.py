#!/usr/bin/env python3
"""Build data/sp500.json from a downloaded Wikipedia constituents page."""
import html
import json
import sys
from html.parser import HTMLParser
from pathlib import Path


class ConstituentsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table=False
        self.in_cell=False
        self.row=[]
        self.rows=[]
        self.text=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=="table" and attrs.get("id")=="constituents": self.in_table=True
        elif self.in_table and tag=="tr": self.row=[]
        elif self.in_table and tag in ("td","th"):
            self.in_cell=True
            self.text=[]

    def handle_data(self, data):
        if self.in_cell: self.text.append(data)

    def handle_endtag(self, tag):
        if self.in_table and tag in ("td","th"):
            self.row.append(html.unescape("".join(self.text)).strip())
            self.in_cell=False
        elif self.in_table and tag=="tr" and len(self.row)>=2: self.rows.append(self.row)
        elif self.in_table and tag=="table": self.in_table=False


def main():
    if len(sys.argv)!=2: raise SystemExit("usage: update_sp500.py downloaded-page.html")
    parser=ConstituentsParser()
    parser.feed(Path(sys.argv[1]).read_text(errors="replace"))
    rows=[[row[0].replace(".","-"),row[1]] for row in parser.rows if row[0]!="Symbol"]
    if len(rows)<490: raise SystemExit(f"unexpected constituent count: {len(rows)}")
    output=Path(__file__).resolve().parents[1]/"data/sp500.json"
    output.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    print(f"wrote {len(rows)} symbols to {output}")


if __name__=="__main__": main()
