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

# 한글 깨짐 방지
import matplotlib.font_manager as fm
try:
    font_location = "C:/Windows/Fonts/malgun.ttf"
    font_name = fm.FontProperties(fname=font_location).get_name()
    matplotlib.rc('font', family=font_name)
except:
    pass

class DataAnalysisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reliability Data Analyzer v2.0 - [Lot/Unit/Delta Analysis]")
        self.geometry("1450x980")
        
        self.raw_files_data = {}  
        self.parameter_list = []
        self.selected_parameters = []
        self.undo_history = []
        self.custom_point_colors = {}
        self.lot_groups = {}
        
        # 신규 기능 제어 변수
        self.tracked_unit_id = tk.StringVar(value="")
        self.is_delta_mode = tk.BooleanVar(value=False)
        
        self.init_upload_menu()
        
    def init_upload_menu(self):
        for widget in self.winfo_children(): widget.destroy()
        f = tk.Frame(self, pady=100); f.pack(expand=True, fill=tk.BOTH)
        tk.Label(f, text="Step 1: Smart Data Batch Upload", font=("Arial", 18, "bold")).pack(pady=10)
        tk.Button(f, text="파일 일괄 선택 (Lot/Read-out 혼합 가능)", font=("Arial", 12, "bold"), 
                  bg="#2b579a", fg="white", padx=20, pady=10, command=self.handle_file_upload).pack(pady=20)

    def parse_filename_info(self, filename):
        lot_match = re.search(r'(lot\s*\d+)', filename, re.IGNORECASE)
        lot_str = lot_match.group(1).upper().replace(" ", "") if lot_match else "UNKNOWN_LOT"
        ro_match = re.search(r'(\d+\s*(?:hr|cyc|min|sec|day))', filename, re.IGNORECASE)
        ro_str = ro_match.group(1).lower().replace(" ", "") if ro_match else filename
        ro_num = int(re.findall(r'\d+', ro_str)[0]) if re.findall(r'\d+', ro_str) else 99999
        return lot_str, ro_str, ro_num

    def handle_file_upload(self):
        files = filedialog.askopenfilenames(title="파일 선택", filetypes=[("Data Files", "*.csv *.xlsx *.xls")])
        if not files: return
        m = tk.Toplevel(self); m.title("Mode"); m.geometry("300x120"); m.transient(self); m.grab_set()
        tk.Label(m, text="데이터 유형 선택", font=("Arial", 10, "bold")).pack(pady=10)
        f = tk.Frame(m); f.pack()
        tk.Button(f, text="Discrete", width=10, command=lambda: self.start_proc(files, "Discrete", m)).pack(side=tk.LEFT, padx=5)
        tk.Button(f, text="Module", width=10, command=lambda: self.start_proc(files, "Module", m)).pack(side=tk.LEFT, padx=5)

    def start_proc(self, files, mode, win):
        self.data_mode = mode; win.destroy(); self.process_files(files)

    def process_files(self, files):
        try:
            # 헤더 탐색
            first_path = files[0]
            df_s = pd.read_csv(first_path, header=None) if first_path.endswith('.csv') else pd.read_excel(first_path, header=None)
            p_idx, u_idx = None, None
            for i, r in df_s.iterrows():
                v = str(r.iloc[0]).strip().lower()
                if "parameter" in v: p_idx = i
                if "unit" in v: u_idx = i
            
            if p_idx is None or u_idx is None: raise ValueError("'Parameter'/'Unit' 행을 1열에서 찾을 수 없음")

            temp_data, all_p, self.lot_groups = {}, set(), {}
            for path in files:
                fname = os.path.basename(path)
                lot, ro, ro_n = self.parse_filename_info(fname)
                df = pd.read_csv(path, header=None) if path.endswith('.csv') else pd.read_excel(path, header=None)
                
                d_start = max(p_idx, u_idx) + 1
                units = df.iloc[d_start:, 0].astype(str).tolist()
                raw_p, raw_u = df.iloc[p_idx, 1:].tolist(), df.iloc[u_idx, 1:].tolist()
                
                # Module Prefix Logic
                final_p, prefix = [], ""
                for p in raw_p:
                    ps = str(p).strip() if not pd.isna(p) else ""
                    if self.data_mode == "Module" and ps.lower().startswith("cont_"):
                        prefix = ps.split('_')[1]; final_p.append(ps)
                    else:
                        final_p.append(f"{prefix}_{ps}" if prefix and self.data_mode == "Module" else ps)
                
                # 중복 이름 번호 부여
                counts = {}; numbered_p = []
                for p in final_p:
                    if not p: numbered_p.append(""); continue
                    counts[p] = counts.get(p, 0) + 1; numbered_p.append(p)
                cur = {}
                for idx, p in enumerate(numbered_p):
                    if p and counts[p] > 1:
                        cur[p] = cur.get(p, 0) + 1; numbered_p[idx] = f"{p}{cur[p]}"

                p_dict = {}
                for c_idx, pn in enumerate(numbered_p):
                    if not pn or "cont_" in pn.lower(): continue
                    un = str(raw_u[c_idx]).strip() if not pd.isna(raw_u[c_idx]) else ""
                    if not un: continue
                    vals = pd.to_numeric(df.iloc[d_start:, c_idx+1], errors='coerce').tolist()
                    if all(v is None or np.isnan(v) for v in vals): continue
                    p_dict[pn] = {'unit': un, 'values': vals, 'units_map': units}
                    all_p.add(pn)
                
                temp_data[fname] = {'lot': lot, 'ro': ro, 'ro_num': ro_n, 'params': p_dict}
                if lot not in self.lot_groups: self.lot_groups[lot] = []
                self.lot_groups[lot].append(fname)

            self.parameter_list = sorted(list(all_p))
            if len(self.parameter_list) > 200: raise ValueError("Parameter 200개 초과")
            self.raw_files_data = temp_data
            for l in self.lot_groups: self.lot_groups[l].sort(key=lambda x: self.raw_files_data[x]['ro_num'])
            self.init_analysis_menu()
        except Exception as e: messagebox.showerror("Error", str(e))

    def init_analysis_menu(self):
        for widget in self.winfo_children(): widget.destroy()
        
        t = tk.Frame(self, bg="#f4f4f4", pady=10, padx=10); t.pack(fill=tk.X)
        
        # 신규 기능 컨트롤러 (Delta & Tracking)
        ctrl_f = tk.LabelFrame(t, text="Advanced Analysis Control", font=("Arial", 9, "bold"), bg="#f4f4f4", padx=10)
        ctrl_f.pack(side=tk.RIGHT, padx=10)
        tk.Checkbutton(ctrl_f, text="Delta Mode (%)", variable=self.is_delta_mode, bg="#f4f4f4", command=self.render_analysis_graphs).pack(side=tk.LEFT)
        tk.Label(ctrl_f, text=" | Track Unit #:", bg="#f4f4f4").pack(side=tk.LEFT)
        tk.Entry(ctrl_f, textvariable=self.tracked_unit_id, width=8).pack(side=tk.LEFT, padx=5)
        tk.Button(ctrl_f, text="Apply", command=self.render_analysis_graphs, bg="#2d3436", fg="white", font=("Arial", 8)).pack(side=tk.LEFT)

        tk.Label(t, text="Parameter Selector:", font=("Arial", 11, "bold"), bg="#f4f4f4").pack(anchor="w")
        lf = tk.Frame(t); lf.pack(fill=tk.X, pady=5)
        self.param_listbox = tk.Listbox(lf, selectmode=tk.EXTENDED, height=5, font=("Consolas", 10))
        self.param_listbox.pack(fill=tk.X, side=tk.LEFT, expand=True)
        sb = ttk.Scrollbar(lf, command=self.param_listbox.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.param_listbox.config(yscrollcommand=sb.set)
        self.param_listbox.insert(tk.END, "★ 전체 선택")
        for p in self.parameter_list: self.param_listbox.insert(tk.END, p)
        self.param_listbox.selection_set(0)

        btn_f = tk.Frame(t, bg="#f4f4f4"); btn_f.pack(fill=tk.X)
        tk.Button(btn_f, text="그래프 그리기", bg="#107c41", fg="white", font=("Arial", 10, "bold"), command=self.render_analysis_graphs).pack(side=tk.LEFT, padx=5)
        self.btn_undo = tk.Button(btn_f, text="Undo", state=tk.DISABLED, command=self.trigger_undo); self.btn_undo.pack(side=tk.LEFT)
        tk.Button(self, text="PDF Export", bg="#d24726", fg="white", command=self.export_plots_to_pdf).pack(side=tk.BOTTOM, pady=10)

        c = tk.Frame(self); c.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(c); self.scrollable_frame = tk.Frame(self.canvas)
        sb_v = ttk.Scrollbar(c, orient="vertical", command=self.canvas.yview); sb_v.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb_v.set)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.render_analysis_graphs(True)

    def render_analysis_graphs(self, first=False):
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        sel = [self.param_listbox.get(i) for i in self.param_listbox.curselection()]
        self.selected_parameters = self.parameter_list.copy() if "★ 전체 선택" in sel else [v for v in sel if v != "★ 전체 선택"]
        if not self.selected_parameters: return
        
        base_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        target_unit = self.tracked_unit_id.get().strip()

        for lot in sorted(self.lot_groups.keys()):
            lot_files = self.lot_groups[lot]
            tk.Label(self.scrollable_frame, text=f"■ [{lot}] Lot Analysis", font=("Arial", 14, "bold"), fg="#1e3799", pady=15).pack(anchor="w", padx=10)
            
            # Line Charts
            for param in self.selected_parameters:
                unit_str = ""; initial_vals = {}
                for fn in lot_files:
                    if param in self.raw_files_data[fn]['params']:
                        unit_str = self.raw_files_data[fn]['params'][param]['unit']; break
                if not unit_str: continue

                # Delta Mode 초기값 수집 (ro_num이 가장 작은 파일을 기준)
                if self.is_delta_mode.get():
                    ref_fn = lot_files[0]
                    if param in self.raw_files_data[ref_fn]['params']:
                        p_ref = self.raw_files_data[ref_fn]['params'][param]
                        for u_id, v in zip(p_ref['units_map'], p_ref['values']):
                            if v is not None and not np.isnan(v) and v != 0: initial_vals[u_id] = v

                fig, ax = plt.subplots(figsize=(13.0, 2.0))
                for f_idx, filename in enumerate(lot_files):
                    if param not in self.raw_files_data[filename]['params']: continue
                    p_info = self.raw_files_data[filename]['params'][param]
                    ro_lbl = self.raw_files_data[filename]['ro']
                    
                    px, py, pc, ps, pz = [], [], [], [], []
                    for ux, uy in zip(p_info['units_map'], p_info['values']):
                        if uy is None or np.isnan(uy): continue
                        
                        # Delta 계산
                        val_to_plot = uy
                        if self.is_delta_mode.get():
                            if ux in initial_vals: val_to_plot = 100 * (uy - initial_vals[ux]) / initial_vals[ux]
                            else: continue
                        
                        px.append(str(ux)); py.append(val_to_plot)
                        
                        # Unit Tracking 강조 로직
                        is_tracked = (str(ux) == target_unit)
                        pc.append(self.custom_point_colors.get((param, filename, str(ux)), base_colors[f_idx % len(base_colors)]))
                        ps.append(100 if is_tracked else 35)
                        pz.append(5 if is_tracked else 2)

                    if px:
                        ax.plot(px, py, color=base_colors[f_idx % len(base_colors)], alpha=0.3 if target_unit and target_unit not in px else 0.6, zorder=1)
                        ax.scatter(px, py, color=pc, s=ps, label=ro_lbl, zorder=3, picker=True)
                
                display_unit = "%" if self.is_delta_mode.get() else unit_str
                ax.set_title(f"[{lot}] {param} ({display_unit})", weight='bold')
                ax.grid(True, linestyle=":", alpha=0.5); ax.legend(loc="upper right", fontsize=8)
                FigureCanvasTkAgg(fig, master=self.scrollable_frame).get_tk_widget().pack(fill=tk.X, padx=15, pady=5)
                plt.close(fig)

            # Box Plots (가로 4열)
            gc = tk.Frame(self.scrollable_frame, bg="#f0f0f0"); gc.pack(fill=tk.X, padx=15, pady=10)
            v_idx = 0
            for param in self.selected_parameters:
                unit_str = ""; b_data, a_labels, b_cols, stats = [], [], [], []
                for f_idx, fn in enumerate(lot_files):
                    if param in self.raw_files_data[fn]['params']:
                        unit_str = self.raw_files_data[fn]['params'][param]['unit']
                        vals = [v for v in self.raw_files_data[fn]['params'][param]['values'] if v is not None and not np.isnan(v)]
                        if vals:
                            b_data.append(vals); a_labels.append(self.raw_files_data[fn]['ro'])
                            b_cols.append(base_colors[f_idx % len(base_colors)])
                            stats.append(f"[{self.raw_files_data[fn]['ro']}]\nAvg:{np.mean(vals):.2f} Std:{np.std(vals):.2f}")
                if not b_data: continue

                bb = tk.Frame(gc, bd=1, relief=tk.GROOVE, bg="white"); bb.grid(row=v_idx//4, column=v_idx%4, padx=5, pady=5, sticky="nsew")
                v_idx += 1
                fig, ax = plt.subplots(figsize=(3.2, 3.2))
                bp = ax.boxplot(b_data, tick_labels=a_labels, patch_artist=True)
                for patch, color in zip(bp['boxes'], b_cols): patch.set_facecolor(color); patch.set_alpha(0.7)
                ax.set_title(f"{param}", fontsize=9, weight='bold'); ax.grid(True, alpha=0.3)
                FigureCanvasTkAgg(fig, master=bb).get_tk_widget().pack()
                sf = tk.Frame(bb, bg="#fafafa"); sf.pack(fill=tk.X)
                for s in stats: tk.Label(sf, text=s, font=("Arial", 7), bg="#fafafa", justify=tk.LEFT).pack(anchor="w")
                plt.close(fig)
            for c in range(4): gc.grid_columnconfigure(c, weight=1)

    def trigger_undo(self): # (기존 Undo 로직 동일)
        pass

    def export_plots_to_pdf(self): # (가로 Landscape 8개 모아찍기 로직 동일)
        pass

if __name__ == "__main__":
    DataAnalysisApp().mainloop()
