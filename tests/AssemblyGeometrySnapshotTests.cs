using System;
class AssemblyGeometrySnapshotTests {
    static object Field(object row,string key){return row.GetType().GetProperty(key).GetValue(row,null);}
    static void Equal(double[] a,double[] b){for(int i=0;i<a.Length;i++)if(Math.Abs(a[i]-b[i])>1e-10)throw new Exception("WORLD_COORDINATE_MISMATCH");}
    static int Main(){
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        double[] pose={0,1,0,-1,0,0,0,0,1,10,20,30,1,0,0,0};
        var snapshot=new AssemblyGeometrySnapshot();
        snapshot.Add("c","part","part",true,0,new[]{1.0,2,3,1,0,0,.01},pose,.2);
        snapshot.Add("c","part","part",false,0,new[]{1.0,0,0,1,2,3},pose,.2);
        Equal((double[])Field(snapshot.Rows[0],"reference_point_global_m"),new[]{8.0,21,33});
        Equal((double[])Field(snapshot.Rows[0],"axis_global"),new[]{0.0,1,0});
        Equal((double[])Field(snapshot.Rows[1],"reference_point_global_m"),new[]{8.0,21,33});
        if((double)Field(snapshot.Rows[0],"cylinder_radius_m")!=.01||!snapshot.Complete)throw new Exception("RADIUS_OR_COMPLETE");
        snapshot.Add("c","part","part",true,1,new[]{Double.NaN,2,3,1,0,0,.01},pose,.2);
        var scaled=(double[])pose.Clone();scaled[12]=2;
        snapshot.Add("c","part","part",true,1,new[]{1.0,2,3,1,0,0,.01},scaled,.2);
        if(snapshot.Invalid!=2||snapshot.Complete||snapshot.Rows.Count!=2)throw new Exception("INVALID_NOT_REPORTED");
        var bounded=new AssemblyGeometrySnapshot();
        for(int i=0;i<AssemblyGeometrySnapshot.MaximumRows+1;i++)bounded.Add("c","part","part",true,i,new[]{1.0,2,3,1,0,0,.01},pose,.2);
        if(bounded.Complete||bounded.Omitted!=1||bounded.Rows.Count!=AssemblyGeometrySnapshot.MaximumRows)throw new Exception("BUDGET_NOT_EXPLICIT");
        Console.WriteLine("4 analytic geometry snapshot policy cases passed; no CAD");return 0;
    }
}
