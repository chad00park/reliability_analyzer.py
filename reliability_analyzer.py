import os
import re
import sys
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.font_manager as fm

# 한글 폰트 설정 (Windows 기본 맑은 고딕 사용)
try:
    font_location = "C:/Windows/Fonts/malgun.ttf"
    font_name = fm.FontProperties(fname=font_location).get_name()
    matplotlib.rc('font', family=font_name)
except Exception:
    pass

class DataAnalysisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reliability Data Analyzer v3.9 - [Optimized]")
        self.geometry("1450x950")
        self.center_window(self, 1450, 950)
        
        # 데이터 저장용 변수 초기화
        self.raw_files_data = {}  
        self.parameter_list = []
        self.selected_parameters = []
        self.lot_groups = {}
        self.lot_display_names = {}
        self.data_mode = "Discrete"
        
        self.custom_colors = {}   
        self.deleted_units = {}    
        self.undo_stack = []       
        
        self.is_delta_mode = tk.BooleanVar(value=False)
        self.init_upload_menu()
        
    def center_window(self, win, w, h):
        win.update_idletasks()
        ws = win.winfo_screenwidth()
        hs = win.winfo_screenheight()
        x = (ws / 2) - (w / 2)
        y = (hs / 2) - (h / 2)
        win.geometry(f'{w}x{h}+{int(x)}+{int(y)}')

    def init_upload_menu(self):
        for widget in self.winfo_children(): 
            widget.destroy()
        
        f = tk.Frame(self, pady=100)
        f.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(f, text="Smart Reliability Data Analyzer", font=("Arial", 18, "bold")).pack(pady=10)
        tk.Button(f, text="파일 일괄 선택 (Lot/Read-out 혼합 가능)", font=("Arial", 12, "bold"), 
                  bg="#2b579a", fg="white", padx=20, pady=10, command=self.handle_file_upload).pack(pady=20)

    def parse_filename_info(self, filename):
        lot_match = re.search(r'(lot\s*\d+)', filename, re.IGNORECASE)
        lot_str = lot_match.group(1).upper().replace(" ", "") if lot_match else "UNKNOWN_LOT"
        
        ro_match = re.search(r'(\d+\s*(?:hr|cyc|min|sec|day))', filename, re.IGNORECASE)
        ro_str = ro_match.group(1).lower().replace(" ", "") if ro_match else filename
        
        ro_num = int(re.findall(r'\d+', ro_str)[0]) if re.findall(r'\d+', ro_str) else 99999
        return lot_str, ro_str, ro_num

    def smart_read_csv_or_excel(self, path):
        if path.endswith('.csv'):
            max_cols = 0
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    col_count = len(line.split(','))
                    if col_count > max_cols: 
                        max_cols = col_count
            return pd.read_csv(path, header=None, names=range(max_cols), engine='python', on_bad_lines='skip')
        else:
            return pd.read_excel(path, header=None)

    def handle_file_upload(self):
        files = filedialog.askopenfilenames(title="파일 선택", filetypes=[("Data Files", "*.csv *.xlsx *.xls")])
        if not files: 
            return
        
        m = tk.Toplevel(self)
        m.title("Mode")
        m.transient(self)
        m.grab_set()
        self.center_window(m, 300, 120)
        
        tk.Label(m, text="데이터 유형 선택", font=("Arial", 10, "bold")).pack(pady=10)
        f = tk.Frame(m)
        f.pack()
        tk.Button(f, text="Discrete", width=10, command=lambda: self.start_proc(files, "Discrete", m)).pack(side=tk.LEFT, padx=5)
        tk.Button(f, text="Module", width=10, command=lambda: self.start_proc(files, "Module", m)).pack(side=tk.LEFT, padx=5)

    def start_proc(self, files, mode, win):
        self.data_mode = mode
        win.destroy()
        self.process_files(files)

    def process_files(self, files):
        try:
            df_s = self.smart_read_csv_or_excel(files[0])
            p_idx, u_idx, sample_start_row = None, None, None
            
            for i, r in df_s.iterrows():
                val_first_col = str(r.iloc[0]).strip().lower().replace(" ", "")
                if "parameter" in val_first_col: p_idx = i
                if "unit" in val_first_col: u_idx = i
                if "sample" in val_first_col: sample_start_row = i

            if p_idx is None or u_idx is None or sample_start_row is None: 
                raise ValueError("파일 내에서 'Parameter', 'Unit' 혹은 'sample' 행을 식별하지 못했습니다.")

            temp_data, all_p, self.lot_groups = {}, set(), {}
            
            for path in files:
                fname = os.path.basename(path)
                lot, ro, ro_n = self.parse_filename_info(fname)
                df = self.smart_read_csv_or_excel(path)
                
                units = df.iloc[sample_start_row + 1:, 0].dropna().astype(str).tolist()
                raw_p = df.iloc[p_idx, 1:].tolist()
                raw_u = df.iloc[u_idx, 1:].tolist()
                
                final_p, prefix = [], ""
                for p in raw_p:
                    ps = str(p).strip() if not pd.isna(p) else ""
                    if self.data_mode == "Module" and ps.lower().startswith("cont_"):
                        prefix = ps.split('_')[1]
                        final_p.append(ps)
                    else:
                        final_p.append(f"{prefix}_{ps}" if prefix and self.data_mode == "Module" else ps)
                
                counts = {}
                numbered_p = []
                for p in final_p:
                    if not p: 
                        numbered_p.append("")
                        continue
                    counts[p] = counts.get(p, 0) + 1
                    numbered_p.append(p)
                
                cur = {}
                for idx, p in enumerate(numbered_p):
                    if p and counts[p] > 1:
                        cur[p] = cur.get(p, 0) + 1
                        numbered_p[idx] = f"{p}{cur[p]}"

                p_dict = {}
                for c_idx, pn in enumerate(numbered_p):
                    if not pn or "cont_" in pn.lower(): 
                        continue
                    un = str(raw_u[c_idx]).strip() if c_idx < len(raw_u) and not pd.isna(raw_u[c_idx]) else ""
                    if not un: 
                        continue
                    
                    vals = pd.to_numeric(df.iloc[sample_start_row + 1:, c_idx + 1], errors='coerce').tolist()
                    vals = vals[:len(units)]
                    
                    if all(v is None or np.isnan(v) for v in vals): 
                        continue
                    p_dict[pn] = {'unit': un, 'values': vals, 'units_map': units[:len(vals)]}
                    all_p.add(pn)
                
                temp_data[fname] = {'lot': lot, 'ro': ro, 'ro_num': ro_n, 'params': p_dict}
                if lot not in self.lot_groups: 
                    self.lot_groups[lot] = []
                self.lot_groups[lot].append(fname)

            self.parameter_list = sorted(list(all_p))
            self.raw_files_data = temp_data
            
            for l in self.lot_groups: 
                self.lot_groups[l].sort(key=lambda x: self.raw_files_data[x]['ro_num'])
                self.lot_display_names[l] = l
                
            self.init_analysis_menu()
        except Exception as e: 
            messagebox.showerror("Error", str(e))

    def init_analysis_menu(self):
        for widget in self.winfo_children(): 
            widget.destroy()
        
        t = tk.Frame(self, bg="#f4f4f4", pady=10, padx=10)
        t.pack(fill=tk.X)
        
        ctrl_f = tk.LabelFrame(t, text="Analysis Control Panel",
